"""
services/document_validation_service.py

Implements case study section 20: validate the uploaded file BEFORE any
OCR/AI extraction is attempted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.image_utils import get_pdf_page_count

logger = get_logger(__name__)


class UnsupportedFileTypeError(Exception):
    pass


@dataclass
class FileValidationOutcome:
    is_supported_format: bool
    is_readable: bool
    is_within_page_limit: bool
    file_type: Optional[str]
    page_count: Optional[int]
    file_size_bytes: Optional[int]
    errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.is_supported_format and self.is_readable and self.is_within_page_limit and not self.errors


def validate_file(file_path: str, original_filename: str) -> FileValidationOutcome:
    settings = get_settings()
    errors: List[str] = []

    ext = os.path.splitext(original_filename)[1].lower()
    is_supported_format = ext in settings.ALLOWED_EXTENSIONS
    if not is_supported_format:
        errors.append(f"Unsupported file extension '{ext}'. Only PDF, JPG, PNG are supported.")

    if not os.path.exists(file_path):
        errors.append("Uploaded file does not exist on disk.")
        return FileValidationOutcome(
            is_supported_format=is_supported_format,
            is_readable=False,
            is_within_page_limit=False,
            file_type=ext.lstrip(".") or None,
            page_count=None,
            file_size_bytes=None,
            errors=errors,
        )

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        errors.append("Uploaded file is empty.")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        errors.append(f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB} MB.")

    is_readable = file_size > 0
    page_count: Optional[int] = None
    is_within_page_limit = True

    if is_supported_format and is_readable:
        if ext == ".pdf":
            try:
                page_count = get_pdf_page_count(file_path)
            except Exception as exc:
                is_readable = False
                errors.append(f"PDF appears to be corrupted or unreadable: {exc}")
            else:
                if page_count > settings.MAX_PAGE_COUNT:
                    is_within_page_limit = False
                    errors.append(
                        f"Document has {page_count} pages; maximum allowed is {settings.MAX_PAGE_COUNT}."
                    )
        else:
            # JPG/PNG -- verify it actually opens as an image.
            try:
                from PIL import Image

                with Image.open(file_path) as img:
                    img.verify()
                page_count = 1
            except Exception as exc:
                is_readable = False
                errors.append(f"Image file appears to be corrupted or unreadable: {exc}")

    return FileValidationOutcome(
        is_supported_format=is_supported_format,
        is_readable=is_readable,
        is_within_page_limit=is_within_page_limit,
        file_type=ext.lstrip(".") or None,
        page_count=page_count,
        file_size_bytes=file_size,
        errors=errors,
    )
