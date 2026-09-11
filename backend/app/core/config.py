"""
core/config.py

Centralized, environment-driven configuration (case study section 29).
Nothing secret is hardcoded here -- everything comes from environment
variables with sane local-development defaults.
"""
import os
from functools import lru_cache
from typing import List


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    # --- General -----------------------------------------------------
    APP_NAME: str = "Document Intelligence Platform"
    ENV: str = os.getenv("ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Database ------------------------------------------------------
    # Local dev defaults to SQLite (file-based). Production MUST set
    # DATABASE_URL to a PostgreSQL connection string, since SQLite files
    # are not persistent on most cloud/free-tier hosts (section 43).
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./document_intelligence.db"
    )

    # --- CORS ------------------------------------------------------------
    CORS_ORIGINS: List[str] = _split_csv(
        os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000,http://127.0.0.1:5500")
    )

    # --- File upload limits ---------------------------------------------
    MAX_PAGE_COUNT: int = int(os.getenv("MAX_PAGE_COUNT", "3"))
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

    # --- OCR --------------------------------------------------------------
    OCR_PROVIDER: str = os.getenv("OCR_PROVIDER", "tesseract")
    OCR_DPI: int = int(os.getenv("OCR_DPI", "300"))
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")

    # --- LLM extraction ----------------------------------------------------
    # LLM_PROVIDER: "gemini" | "rule_based"
    #
    # "gemini" uses Google's Gemini models through Google's OpenAI-compatible
    # endpoint (https://ai.google.dev/gemini-api/docs/openai) -- we use the
    # official `openai` Python SDK purely as a REST client, pointed at
    # Google's base URL, NOT at OpenAI's own API service. No OpenAI API key
    # is required or used anywhere in this project.
    #
    # When LLM_PROVIDER=gemini but LLM_API_KEY is empty (or the "openai"
    # package is unavailable), the system automatically and safely falls
    # back to the deterministic rule_based provider so the pipeline keeps
    # working end-to-end (with reduced semantic understanding) even without
    # network access / an API key -- see providers/extraction_providers.py.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "rule_based")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))

    # Google's documented OpenAI-compatible Gemini endpoint. Overridable via
    # env var for testing purposes only -- this must NEVER be pointed at
    # https://api.openai.com/ (see providers/extraction_providers.py, which
    # also refuses to do so defensively).
    GEMINI_BASE_URL: str = os.getenv(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
    )

    # --- Validation tolerances --------------------------------------------
    VALIDATION_ABS_TOLERANCE: float = float(os.getenv("VALIDATION_ABS_TOLERANCE", "0.01"))
    VALIDATION_REL_TOLERANCE: float = float(os.getenv("VALIDATION_REL_TOLERANCE", "0.001"))

    # --- API ----------------------------------------------------------------
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")


@lru_cache
def get_settings() -> Settings:
    return Settings()
