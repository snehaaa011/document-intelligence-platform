"""
repositories/document_repository.py

Persistence layer (case study section 23/24). Isolates all direct
SQLAlchemy usage so services/document_service.py never imports the ORM
model or session directly -- this makes the storage backend swappable and
keeps unit tests simple (they can use a fake repository).
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.document import DocumentRecord


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> DocumentRecord:
        record = DocumentRecord(**kwargs)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_latest_by_name(self, document_name: str) -> Optional[DocumentRecord]:
        return (
            self.db.query(DocumentRecord)
            .filter(DocumentRecord.document_name == document_name)
            .order_by(desc(DocumentRecord.created_at))
            .first()
        )

    def list_all(self, limit: int = 200) -> List[DocumentRecord]:
        return (
            self.db.query(DocumentRecord)
            .order_by(desc(DocumentRecord.created_at))
            .limit(limit)
            .all()
        )

    def count(self) -> int:
        return self.db.query(DocumentRecord).count()
