"""
utils/evidence_utils.py

Optional, EXPLAINABLE confidence scoring (case study section 13).

Confidence is deliberately NOT an arbitrary LLM-reported number. It is
computed from four transparent, inspectable components:

    1. ocr_quality        - mean Tesseract word confidence for OCR'd pages
                             (1.0 for pages that used the native PDF text
                             layer, since no OCR uncertainty applies there)
    2. source_text_match   - fraction of extracted evidence values that
                             carry a non-empty source_text/raw_text,
                             i.e. are actually grounded in the document
    3. extraction_completeness - fraction of the canonical fields for this
                             document type that were populated (non-null)
    4. validation_consistency  - fraction of applicable validation checks
                             that passed

Overall confidence = weighted average of the four components. Any
component that cannot be computed (e.g. no validation checks were
applicable) is excluded from the average rather than penalizing the score
with a fabricated zero.
"""
from __future__ import annotations

from typing import List, Optional


def compute_confidence(
    ocr_quality: Optional[float],
    source_text_match: Optional[float],
    extraction_completeness: Optional[float],
    validation_consistency: Optional[float],
) -> Optional[float]:
    weights = {
        "ocr_quality": 0.25,
        "source_text_match": 0.25,
        "extraction_completeness": 0.25,
        "validation_consistency": 0.25,
    }
    components = {
        "ocr_quality": ocr_quality,
        "source_text_match": source_text_match,
        "extraction_completeness": extraction_completeness,
        "validation_consistency": validation_consistency,
    }
    available = {k: v for k, v in components.items() if v is not None}
    if not available:
        return None

    total_weight = sum(weights[k] for k in available)
    score = sum(weights[k] * v for k, v in available.items()) / total_weight
    return round(max(0.0, min(1.0, score)), 4)


def source_text_match_ratio(evidence_values: List[object]) -> Optional[float]:
    """`evidence_values` is a list of EvidenceValue-like objects (duck-typed
    to avoid a circular import on the pydantic schema)."""
    populated = [e for e in evidence_values if e is not None and getattr(e, "value", None) is not None]
    if not populated:
        return None
    grounded = [e for e in populated if getattr(e, "source_text", None) or getattr(e, "raw_text", None)]
    return len(grounded) / len(populated)
