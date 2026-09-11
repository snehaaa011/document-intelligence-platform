"""
api/routes/documents.py

Implements the mandatory REST API (case study section 21):
    POST /api/v1/documents/process
    GET  /api/v1/documents/{document_name}
    GET  /api/v1/documents
    GET  /api/v1/health
"""
import os
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db, engine
from app.core.logging import get_logger
from app.schemas.document import (
    DocumentProcessResponse,
    DocumentListResponse,
    DocumentListItem,
    HealthResponse,
    DocumentType,
)
from app.services.document_service import DocumentService
from app.repositories.document_repository import DocumentRepository
from app.providers.extraction_providers import get_effective_provider_name

router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check(db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        app_name=settings.APP_NAME,
        env=settings.ENV,
        llm_provider=settings.LLM_PROVIDER,
        llm_provider_effective=get_effective_provider_name(),
        ocr_provider=settings.OCR_PROVIDER,
        database_connected=db_ok,
    )


@router.post("/documents/process", response_model=DocumentProcessResponse, tags=["documents"])
async def process_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    db: Session = Depends(get_db),
):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    temp_path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}{ext}")

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"code": "UPLOAD_FAILED", "message": str(exc)})

    logger.info("Processing document name=%s type=%s", file.filename, document_type.value)

    try:
        service = DocumentService(db)
        result = service.process_document(temp_path, file.filename, document_type.value)
        return result
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@router.get("/documents/{document_name}", response_model=DocumentProcessResponse, tags=["documents"])
def get_document(document_name: str, db: Session = Depends(get_db)):
    repo = DocumentRepository(db)
    record = repo.get_latest_by_name(document_name)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": f"No processed document named '{document_name}' was found."})

    from app.schemas.document import FileValidationResult, ProcessingMetadata, ValidationSummary, ErrorDetail

    return DocumentProcessResponse(
        document_name=record.document_name,
        document_type=record.document_type,
        processing_status=record.processing_status,
        overall_confidence=float(record.overall_confidence) if record.overall_confidence else None,
        file_validation=FileValidationResult(**record.file_validation_json) if record.file_validation_json else FileValidationResult(is_supported_format=True, is_readable=True, is_within_page_limit=True),
        extracted_data=record.extracted_data_json,
        validation=ValidationSummary(**record.validation_json) if record.validation_json else None,
        processing_metadata=ProcessingMetadata(**record.processing_metadata_json),
        error=ErrorDetail(**record.error_json) if record.error_json else None,
    )


@router.get("/documents", response_model=DocumentListResponse, tags=["documents"])
def list_documents(db: Session = Depends(get_db)):
    repo = DocumentRepository(db)
    records = repo.list_all()
    return DocumentListResponse(
        total=repo.count(),
        documents=[
            DocumentListItem(
                document_name=r.document_name,
                document_type=r.document_type,
                processing_status=r.processing_status,
                created_at=r.created_at,
            )
            for r in records
        ],
    )
