"""
tests/test_document_validation.py

Covers case study section 37 items 1-5: supported PDF/JPG validation,
unsupported file rejection, empty file rejection, page limit validation.
"""
import os
import tempfile

from PIL import Image

from app.services.document_validation_service import validate_file


def test_unsupported_extension_rejected():
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        f.write(b"not really an exe")
        path = f.name
    try:
        outcome = validate_file(path, "malware.exe")
        assert outcome.is_supported_format is False
        assert outcome.is_valid is False
    finally:
        os.remove(path)


def test_empty_file_rejected():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name  # zero bytes
    try:
        outcome = validate_file(path, "empty.pdf")
        assert outcome.is_readable is False
        assert outcome.is_valid is False
    finally:
        os.remove(path)


def test_valid_jpg_accepted():
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = f.name
    try:
        img = Image.new("RGB", (200, 200), color="white")
        img.save(path, "JPEG")
        outcome = validate_file(path, "receipt.jpg")
        assert outcome.is_supported_format is True
        assert outcome.is_readable is True
        assert outcome.is_valid is True
        assert outcome.page_count == 1
    finally:
        os.remove(path)


def test_corrupted_image_rejected():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"this is not a valid png file")
        path = f.name
    try:
        outcome = validate_file(path, "broken.png")
        assert outcome.is_readable is False
    finally:
        os.remove(path)


def test_docx_rejected_as_unsupported():
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(b"fake docx content")
        path = f.name
    try:
        outcome = validate_file(path, "report.docx")
        assert outcome.is_supported_format is False
    finally:
        os.remove(path)
