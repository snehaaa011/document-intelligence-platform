"""
providers/ocr_providers.py

OCR provider abstraction (case study section 6):

    OCRProvider
        +-- TesseractOCRProvider   (local, free, default)
        +-- (extension point for a cloud OCR provider, e.g. AWS Textract /
             Google Document AI, without changing calling code)

Every provider returns a PageOCRResult per page so page boundaries are
always preserved (section 9/12 require per-page evidence).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

import pytesseract
from PIL import Image

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.image_utils import preprocess_for_ocr

logger = get_logger(__name__)


@dataclass
class PageOCRResult:
    page_number: int
    text: str
    ocr_used: bool
    preprocessing_steps: List[str] = field(default_factory=list)
    mean_word_confidence: float = 0.0  # 0-100, from Tesseract, used for OCR-quality signal


class OCRProvider(ABC):
    @abstractmethod
    def run(self, image: Image.Image, page_number: int) -> PageOCRResult:
        ...


def _reconstruct_rows_from_word_boxes(data: dict, row_tolerance_px: int = 12) -> str:
    """Cluster Tesseract word boxes into visual rows and join left-to-right.

    This is deliberately simple (a greedy vertical-proximity clustering
    rather than full layout analysis) but is robust enough for the
    tabular financial-statement and invoice layouts in the target dataset.
    """
    n = len(data.get("text", []))
    words = []
    for i in range(n):
        token = data["text"][i].strip()
        if not token:
            continue
        words.append((data["top"][i], data["left"][i], token))

    if not words:
        return ""

    words.sort(key=lambda w: (w[0], w[1]))

    rows: list[list[tuple[int, str]]] = []
    current_row: list[tuple[int, str]] = []
    current_top: Optional[int] = None

    for top, left, token in words:
        if current_top is None or abs(top - current_top) <= row_tolerance_px:
            current_row.append((left, token))
            current_top = top if current_top is None else current_top
        else:
            rows.append(current_row)
            current_row = [(left, token)]
            current_top = top
    if current_row:
        rows.append(current_row)

    lines = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        lines.append(" ".join(tok for _, tok in row))
    return "\n".join(lines)


class TesseractOCRProvider(OCRProvider):
    """Local, free OCR using Tesseract via pytesseract."""

    def __init__(self):
        settings = get_settings()
        if settings.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

    def run(self, image: Image.Image, page_number: int) -> PageOCRResult:
        pre = preprocess_for_ocr(image)
        try:
            data = pytesseract.image_to_data(
                pre.processed_image, config='--psm 6', output_type=pytesseract.Output.DICT
            )
            confidences = [
                float(c) for c in data.get("conf", []) if c not in ("-1", -1)
            ]
            mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
            # Tesseract's default reading order groups text into
            # blocks/columns which can scramble tabular rows (e.g. a label
            # column, a schedule-number column and a values column end up
            # as separate blocks rather than interleaved rows). We instead
            # reconstruct rows purely from word bounding boxes: cluster
            # words whose vertical center is close together into the same
            # row, then sort left-to-right within the row. This preserves
            # "label value1 value2" alignment which both the rule-based
            # extractor and the LLM extractor rely on.
            text = _reconstruct_rows_from_word_boxes(data)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Tesseract OCR failed on page %s: %s", page_number, exc)
            text = ""
            mean_conf = 0.0

        return PageOCRResult(
            page_number=page_number,
            text=text,
            ocr_used=True,
            preprocessing_steps=pre.applied_steps,
            mean_word_confidence=mean_conf,
        )


def get_ocr_provider() -> OCRProvider:
    settings = get_settings()
    if settings.OCR_PROVIDER == "tesseract":
        return TesseractOCRProvider()
    # Extension point: add cloud providers here (e.g. "textract", "docai").
    logger.warning(
        "Unknown OCR_PROVIDER=%s, falling back to tesseract", settings.OCR_PROVIDER
    )
    return TesseractOCRProvider()


