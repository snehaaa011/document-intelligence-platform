"""
utils/image_utils.py

Image preprocessing helpers used before OCR (case study section 7).

We deliberately do NOT apply every possible transform to every image --
aggressive preprocessing (e.g. binarization) can destroy information on
already-clean, high-resolution scans. Instead we inspect basic image
statistics and apply a conservative pipeline, keeping the original image
around for evidence/debugging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageOps
import cv2


@dataclass
class PreprocessResult:
    processed_image: Image.Image
    original_image: Image.Image
    applied_steps: list


def _estimate_blur(gray: np.ndarray) -> float:
    """Variance of Laplacian -- low value indicates a blurry/noisy image."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _estimate_brightness(gray: np.ndarray) -> float:
    return float(gray.mean())


def preprocess_for_ocr(image: Image.Image, aggressive: Optional[bool] = None) -> PreprocessResult:
    """
    Apply a conservative, evidence-preserving preprocessing pipeline:
        1. Correct EXIF-based orientation.
        2. Convert to grayscale for analysis.
        3. If the image is small/blurry/noisy (typical of a phone photo of
           a paper document), apply denoising + adaptive contrast + a mild
           sharpen. Otherwise leave a clean, already-scanned document alone
           to avoid losing thin table lines / small fonts.
    """
    steps = []
    original = image.copy()

    corrected = ImageOps.exif_transpose(image) or image
    if corrected is not image:
        steps.append("exif_orientation_correction")

    rgb = corrected.convert("RGB")
    cv_img = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    blur_score = _estimate_blur(gray)
    brightness = _estimate_brightness(gray)
    small_image = min(rgb.size) < 1000

    needs_aggressive = aggressive
    if needs_aggressive is None:
        needs_aggressive = blur_score < 150 or small_image or brightness < 90

    if needs_aggressive:
        # Denoise while preserving edges, then boost local contrast.
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        steps.append("denoise")

        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        contrasted = clahe.apply(denoised)
        steps.append("adaptive_contrast_clahe")

        sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(contrasted, -1, sharpen_kernel)
        steps.append("sharpen")

        final = sharpened
    else:
        # Already a clean scan/printout -- just grayscale + mild contrast.
        clahe = cv2.createCLAHE(clipLimit=1.2, tileGridSize=(8, 8))
        final = clahe.apply(gray)
        steps.append("mild_contrast_clahe")

    processed = Image.fromarray(final)
    return PreprocessResult(processed_image=processed, original_image=original, applied_steps=steps)


def render_pdf_page_to_image(pdf_path: str, page_number: int, dpi: int = 300) -> Image.Image:
    """
    Render a single PDF page (1-indexed) to a PIL Image using the `pdftoppm`
    CLI (poppler-utils), avoiding a hard dependency on PyMuPDF so the
    project also runs in minimal environments that only have poppler
    installed. If PyMuPDF is available it can be swapped in via the
    OCRProvider abstraction without touching calling code.
    """
    import subprocess
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp:
        out_prefix = os.path.join(tmp, "page")
        subprocess.run(
            [
                "pdftoppm",
                "-r", str(dpi),
                "-png",
                "-f", str(page_number),
                "-l", str(page_number),
                pdf_path,
                out_prefix,
            ],
            check=True,
            capture_output=True,
        )
        produced = sorted(
            f for f in os.listdir(tmp) if f.startswith("page") and f.endswith(".png")
        )
        if not produced:
            raise RuntimeError(f"pdftoppm produced no output for page {page_number}")
        return Image.open(os.path.join(tmp, produced[0])).convert("RGB")


def get_pdf_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF using `pdfinfo` (poppler-utils)."""
    import subprocess

    result = subprocess.run(
        ["pdfinfo", pdf_path], check=True, capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if line.lower().startswith("pages:"):
            return int(line.split(":")[1].strip())
    raise RuntimeError("Could not determine PDF page count")


def extract_native_pdf_text(pdf_path: str, page_number: int) -> str:
    """Extract native (non-OCR) text layer from a PDF page using `pdftotext`.
    Returns an empty string if the page has no usable text layer (i.e. it
    is a scanned/flattened image), which the caller uses to decide whether
    OCR is required for that page."""
    import subprocess

    result = subprocess.run(
        [
            "pdftotext",
            "-layout",
            "-f", str(page_number),
            "-l", str(page_number),
            pdf_path,
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
