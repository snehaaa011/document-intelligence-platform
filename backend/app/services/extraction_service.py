"""
services/extraction_service.py

Thin orchestration layer between OCR output and the ExtractionProvider
abstraction (case study section 6/8). Kept separate from
providers/extraction_providers.py so swapping/mocking providers in tests
doesn't require touching pipeline orchestration code.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.providers.extraction_providers import (
    get_extraction_provider,
    ExtractionProviderError,
)
from app.schemas.extraction import ExtractionResult

logger = get_logger(__name__)


class ExtractionService:
    def __init__(self, provider=None):
        self.provider = provider or get_extraction_provider()

    def extract(self, document_type: str, ocr_text: str, page_count: int) -> ExtractionResult:
        try:
            result = self.provider.extract(document_type, ocr_text, page_count)
            result.provider_name = result.provider_name or self.provider.name
            return result
        except ExtractionProviderError as exc:
            logger.error("Extraction failed with provider %s: %s", self.provider.name, exc)
            raise
