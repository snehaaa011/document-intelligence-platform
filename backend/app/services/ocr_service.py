"""
services/ocr_service.py

Orchestrates stages 4-11 of the processing pipeline (case study section 6):
    - Convert PDF pages to images when necessary
    - Detect whether usable native PDF text exists
    - Extract native text when available (fast path, no OCR needed)
    - Run OCR for scanned/image documents
    - Preserve page boundaries and OCR text for evidence

A page is considered to have a "usable" native text layer if extracted
text exceeds a minimal length threshold; short/empty text (typical of a
flattened/scanned "Print to PDF" page, as seen throughout the supplied
HDFC financial statements) triggers the OCR fallback for that page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from PIL import Image

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.ocr_providers import get_ocr_provider, PageOCRResult
from app.utils.image_utils import (
    render_pdf_page_to_image,
    get_pdf_page_count,
    extract_native_pdf_text,
)

logger = get_logger(__name__)

NATIVE_TEXT_MIN_CHARS = 40  # below this, treat the page as image-only


@dataclass
class DocumentOCRResult:
    pages: List[PageOCRResult] = field(default_factory=list)
    page_images: List[Image.Image] = field(default_factory=list)
    any_ocr_used: bool = False

    @property
    def combined_text(self) -> str:
        return "\n\n".join(
            f"--- PAGE {p.page_number} ---\n{p.text}" for p in self.pages
        )


class OCRService:
    def __init__(self):
        self.ocr_provider = get_ocr_provider()
        self.settings = get_settings()

    def process_pdf(self, pdf_path: str) -> DocumentOCRResult:
        page_count = get_pdf_page_count(pdf_path)
        result = DocumentOCRResult()

        for page_num in range(1, page_count + 1):
            native_text = ""
            try:
                native_text = extract_native_pdf_text(pdf_path, page_num)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Native text extraction failed on page %s: %s", page_num, exc)

            image = render_pdf_page_to_image(pdf_path, page_num, dpi=self.settings.OCR_DPI)
            result.page_images.append(image)

            if len(native_text) >= NATIVE_TEXT_MIN_CHARS:
                logger.info("Page %s: using native PDF text layer (%d chars)", page_num, len(native_text))
                result.pages.append(
                    PageOCRResult(page_number=page_num, text=native_text, ocr_used=False)
                )
            else:
                logger.info("Page %s: no usable native text, running OCR", page_num)
                ocr_result = self.ocr_provider.run(image, page_num)
                result.pages.append(ocr_result)
                result.any_ocr_used = True

        return result

    def process_image(self, image_path: str) -> DocumentOCRResult:
        image = Image.open(image_path)
        ocr_result = self.ocr_provider.run(image, page_number=1)
        return DocumentOCRResult(
            pages=[ocr_result], page_images=[image], any_ocr_used=True
        )
