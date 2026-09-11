"""
services/document_service.py

The end-to-end orchestrator (case study section 6 pipeline, sections 19-20
processing-status semantics). This is the ONLY place that stitches together:

    file validation -> OCR -> extraction -> financial validation ->
    confidence -> persistence -> API response

Everything else (OCR provider, extraction provider, validation engine) is
a pure, independently-testable unit used here.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import (
    DocumentProcessResponse,
    FileValidationResult,
    ProcessingMetadata,
    ErrorDetail,
)
from app.services.document_validation_service import validate_file, FileValidationOutcome
from app.services.ocr_service import OCRService
from app.services.extraction_service import ExtractionService
from app.services.financial_validation_service import run_validation
from app.utils.evidence_utils import compute_confidence, source_text_match_ratio
from app.providers.extraction_providers import ExtractionProviderError

logger = get_logger(__name__)


class DocumentProcessingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class DocumentService:
    def __init__(self, db: Session):
        self.settings = get_settings()
        self.repo = DocumentRepository(db)
        self.ocr_service = OCRService()
        self.extraction_service = ExtractionService()

    def process_document(self, file_path: str, original_filename: str, document_type: str) -> DocumentProcessResponse:
        start = time.perf_counter()
        stage_reached = "file_validation"

        file_outcome = validate_file(file_path, original_filename)
        file_validation_schema = FileValidationResult(
            is_supported_format=file_outcome.is_supported_format,
            is_readable=file_outcome.is_readable,
            is_within_page_limit=file_outcome.is_within_page_limit,
            file_type=file_outcome.file_type,
            page_count=file_outcome.page_count,
            file_size_bytes=file_outcome.file_size_bytes,
            errors=file_outcome.errors,
        )

        if not file_outcome.is_valid:
            return self._finalize_failed(
                original_filename, document_type, file_validation_schema,
                error_code="FILE_VALIDATION_FAILED",
                error_message="; ".join(file_outcome.errors) or "File failed validation.",
                stage_reached=stage_reached,
                start=start,
            )

        try:
            stage_reached = "ocr"
            ext = file_outcome.file_type
            if ext == "pdf":
                ocr_result = self.ocr_service.process_pdf(file_path)
            else:
                ocr_result = self.ocr_service.process_image(file_path)

            stage_reached = "extraction"
            extraction = self.extraction_service.extract(
                document_type, ocr_result.combined_text, len(ocr_result.pages)
            )

            stage_reached = "validation"
            validation = run_validation(document_type, extraction)

            stage_reached = "confidence"
            confidence = self._compute_confidence(extraction, ocr_result, validation)

            stage_reached = "persistence"
            status = "FAILED" if _has_critical_missing(extraction, document_type) else "PASS"

            processing_time_ms = int((time.perf_counter() - start) * 1000)
            metadata = ProcessingMetadata(
                ocr_used=ocr_result.any_ocr_used,
                extraction_provider=extraction.provider_name,
                processed_at=datetime.now(timezone.utc),
                processing_time_ms=processing_time_ms,
                pipeline_stage_reached="completed",
            )

            extracted_dict = extraction.model_dump()

            self.repo.create(
                id=str(uuid.uuid4()),
                document_name=original_filename,
                document_type=document_type,
                processing_status=status,
                file_type=file_outcome.file_type,
                page_count=file_outcome.page_count,
                is_supported=file_outcome.is_supported_format,
                is_readable=file_outcome.is_readable,
                overall_confidence=str(confidence) if confidence is not None else None,
                file_validation_json=file_validation_schema.model_dump(),
                extracted_data_json=extracted_dict,
                validation_json=validation.model_dump(),
                processing_metadata_json=metadata.model_dump(mode="json"),
                error_json=None,
            )

            return DocumentProcessResponse(
                document_name=original_filename,
                document_type=document_type,
                processing_status=status,
                overall_confidence=confidence,
                file_validation=file_validation_schema,
                extracted_data=extracted_dict,
                validation=validation,
                processing_metadata=metadata,
                error=None,
            )

        except ExtractionProviderError as exc:
            return self._finalize_failed(
                original_filename, document_type, file_validation_schema,
                error_code="EXTRACTION_FAILED", error_message=str(exc),
                stage_reached=stage_reached, start=start,
            )
        except Exception as exc:  # pragma: no cover - defensive, never leak stack trace to client
            logger.exception("Unexpected processing error at stage %s", stage_reached)
            return self._finalize_failed(
                original_filename, document_type, file_validation_schema,
                error_code="PROCESSING_ERROR",
                error_message=f"Unexpected error during {stage_reached}. See server logs for details.",
                stage_reached=stage_reached, start=start,
            )

    def _compute_confidence(self, extraction, ocr_result, validation) -> Optional[float]:
        ocr_confidences = [p.mean_word_confidence for p in ocr_result.pages if p.ocr_used]
        ocr_quality = (sum(ocr_confidences) / len(ocr_confidences) / 100.0) if ocr_confidences else 1.0

        # Gather evidence objects for source-text-match and completeness ratios.
        evidence_objs = []
        if extraction.invoice_fields:
            for field_name in ["invoice_number","invoice_date","due_date","subtotal","discount_amount","tax_amount","shipping_amount","total_amount","amount_paid","amount_due","cash_tendered","change_returned"]:
                val = getattr(extraction.invoice_fields, field_name, None)
                if val is not None:
                    evidence_objs.append(val)
        for item in extraction.statement_line_items:
            for p in item.periods:
                evidence_objs.append(p.evidence)

        source_match = source_text_match_ratio(evidence_objs)

        applicable = [c for c in validation.checks if c.status != "NOT_APPLICABLE"]
        validation_consistency = (
            sum(1 for c in applicable if c.status == "PASS") / len(applicable) if applicable else None
        )

        populated = sum(1 for e in evidence_objs if getattr(e, "value", None) is not None)
        completeness = (populated / len(evidence_objs)) if evidence_objs else None

        return compute_confidence(ocr_quality, source_match, completeness, validation_consistency)

    def _finalize_failed(self, original_filename, document_type, file_validation_schema, error_code, error_message, stage_reached, start) -> DocumentProcessResponse:
        processing_time_ms = int((time.perf_counter() - start) * 1000)
        metadata = ProcessingMetadata(
            ocr_used=False,
            extraction_provider=None,
            processed_at=datetime.now(timezone.utc),
            processing_time_ms=processing_time_ms,
            pipeline_stage_reached=stage_reached,
        )
        self.repo.create(
            id=str(uuid.uuid4()),
            document_name=original_filename,
            document_type=document_type,
            processing_status="FAILED",
            file_type=file_validation_schema.file_type,
            page_count=file_validation_schema.page_count,
            is_supported=file_validation_schema.is_supported_format,
            is_readable=file_validation_schema.is_readable,
            overall_confidence=None,
            file_validation_json=file_validation_schema.model_dump(),
            extracted_data_json=None,
            validation_json=None,
            processing_metadata_json=metadata.model_dump(mode="json"),
            error_json={"code": error_code, "message": error_message},
        )
        return DocumentProcessResponse(
            document_name=original_filename,
            document_type=document_type,
            processing_status="FAILED",
            overall_confidence=None,
            file_validation=file_validation_schema,
            extracted_data=None,
            validation=None,
            processing_metadata=metadata,
            error=ErrorDetail(code=error_code, message=error_message),
        )


def _has_critical_missing(extraction, document_type: str) -> bool:
    """Distinguish a genuine processing failure from a financial-validation
    FAIL (section 19): only treat as FAILED if essentially nothing useful
    was extracted at all."""
    if document_type == "invoice":
        f = extraction.invoice_fields
        return f is None or (f.total_amount is None and f.subtotal is None and not extraction.invoice_line_items)
    return not extraction.statement_line_items
