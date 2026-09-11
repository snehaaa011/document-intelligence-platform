"""
core/logging.py

Simple structured logging setup (case study section 31).

Rules enforced by convention across the codebase (reviewers/CI could add a
log-scrubbing filter here too):
    - Never log LLM_API_KEY, DATABASE_URL credentials, or raw file bytes.
    - Always include document_name / document_type / stage / duration_ms
      where relevant so failures are traceable to a pipeline stage.
"""
import logging
import sys

from app.core.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
