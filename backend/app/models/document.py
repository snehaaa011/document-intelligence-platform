"""
models/document.py

SQLAlchemy model for persisted processing results (case study section 24).
Deliberately not over-engineered: extracted/validation/metadata payloads are
stored as JSON blobs (JSONB under Postgres, TEXT/JSON under SQLite) rather
than being fully normalized into dozens of tables, which would add
significant complexity for no benefit at this project's scale.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.core.config import get_settings

settings = get_settings()

# Use native JSONB on Postgres, fall back to generic JSON (works on SQLite)
JSONType = JSONB if settings.DATABASE_URL.startswith("postgresql") else JSON


def _uuid() -> str:
    return str(uuid.uuid4())


class DocumentRecord(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    document_name = Column(String, index=True, nullable=False)
    document_type = Column(String, index=True, nullable=False)
    processing_status = Column(String, index=True, nullable=False)  # PASS | FAILED

    file_type = Column(String, nullable=True)
    page_count = Column(Integer, nullable=True)
    is_supported = Column(Boolean, default=True)
    is_readable = Column(Boolean, default=True)

    overall_confidence = Column(String, nullable=True)  # stored as string; None if not implemented

    file_validation_json = Column(JSONType, nullable=True)
    extracted_data_json = Column(JSONType, nullable=True)
    validation_json = Column(JSONType, nullable=True)
    processing_metadata_json = Column(JSONType, nullable=True)
    error_json = Column(JSONType, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
