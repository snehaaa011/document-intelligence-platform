"""
number_parser.py

Robust financial-number normalization utilities.

Design goal (see case study section 10/11):
    - Never destroy the originally displayed value -> callers should keep
      the raw OCR/source string alongside the normalized float.
    - Support currency symbols, thousands separators, parentheses/brackets
      as negative indicators, unit-scale words (crore / lakh / thousand /
      million), and percentages.
    - Be forgiving of common OCR mistakes (O -> 0, l/I -> 1, stray spaces,
      double dots) WITHOUT inventing digits that are not present.

This module contains pure functions with no external dependencies so it can
be unit-tested in complete isolation from FastAPI / DB / OCR / LLM layers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Currency symbol / code table
# ---------------------------------------------------------------------------
CURRENCY_SYMBOLS = {
    "₹": "INR",
    "रु": "INR",
    "Rs.": "INR",
    "Rs": "INR",
    "INR": "INR",
    "$": "USD",
    "USD": "USD",
    "US$": "USD",
    "CAD": "CAD",
    "C$": "CAD",
    "RM": "MYR",
    "MYR": "MYR",
    "£": "GBP",
    "GBP": "GBP",
    "€": "EUR",
    "EUR": "EUR",
}

# Ordered longest-first so multi-character symbols match before single chars.
_SORTED_SYMBOLS = sorted(CURRENCY_SYMBOLS.keys(), key=len, reverse=True)

# Unit-scale multipliers as used in Indian and international financial
# statements. NOTE: we intentionally do NOT auto-multiply values -- the
# scale is reported separately (see unit_scale field) because collapsing
# it into the raw number would hide the source representation.
UNIT_SCALE_WORDS = {
    "crore": "crore",
    "cr": "crore",
    "lakh": "lakh",
    "lac": "lakh",
    "thousand": "thousand",
    "'000": "thousand",
    "000s": "thousand",
    "million": "million",
    "mn": "million",
    "billion": "billion",
    "bn": "billion",
}

_OCR_DIGIT_FIXES = {
    "O": "0",
    "o": "0",
    "l": "1",
    "I": "1",
    "S": "5",  # only applied inside numeric-looking tokens, see _looks_numeric
}


@dataclass
class ParsedNumber:
    """Result of parsing a raw numeric/currency string."""

    raw_text: str
    value: Optional[float]
    currency: Optional[str] = None
    is_negative: bool = False
    is_percentage: bool = False
    unit_scale: Optional[str] = None
    ocr_corrected: bool = False


def _looks_numeric(token: str) -> bool:
    """Heuristic: token is 'mostly' digits/punctuation so OCR letter->digit
    substitution is safe to attempt."""
    digit_like = sum(ch.isdigit() for ch in token)
    letter_like = sum(ch.isalpha() for ch in token)
    return digit_like >= letter_like and digit_like > 0


def _fix_ocr_digit_noise(token: str) -> tuple[str, bool]:
    """Conservatively swap common OCR letter/digit confusions, but only
    inside tokens that already look numeric, and only when doing so keeps
    the token a valid-looking number. We never guess a digit that isn't
    represented by *some* character in the source."""
    if not _looks_numeric(token):
        return token, False
    corrected = []
    changed = False
    for ch in token:
        if ch in _OCR_DIGIT_FIXES:
            corrected.append(_OCR_DIGIT_FIXES[ch])
            changed = True
        else:
            corrected.append(ch)
    return "".join(corrected), changed


def detect_currency(text: str) -> Optional[str]:
    """Find the first recognizable currency symbol/code in free text."""
    for sym in _SORTED_SYMBOLS:
        if sym in text:
            return CURRENCY_SYMBOLS[sym]
    return None


def detect_unit_scale(text: str) -> Optional[str]:
    """Find a unit-scale hint such as 'in crore' / 'in '000' / 'RM million'."""
    lowered = text.lower()
    for word, canonical in UNIT_SCALE_WORDS.items():
        if word in lowered:
            return canonical
    return None


def parse_amount(raw: str, assume_currency: Optional[str] = None) -> ParsedNumber:
    """
    Parse a single displayed monetary/numeric value into a normalized float.

    Handles:
        (1,234.50)   -> -1234.50
        ₹ 6,862.00   -> 6862.00, currency=INR
        1,000,000    -> 1000000.0
        9%           -> 0.09  (is_percentage=True, value stores the decimal
                                 fraction; raw_text preserves "9%")
        RM 8.49      -> 8.49, currency=MYR
        -            -> None  (dash used as "not present" placeholder)

    Returns ParsedNumber(value=None, ...) when the string does not contain a
    usable numeric value (e.g. blank, '-', 'N/A'); callers must then store
    null rather than fabricate a number.
    """
    if raw is None:
        return ParsedNumber(raw_text="", value=None)

    original = raw
    text = raw.strip()

    if text in {"", "-", "--", "—", "N/A", "NA", "n/a", "Nil", "NIL"}:
        return ParsedNumber(raw_text=original, value=None)

    currency = detect_currency(text) or assume_currency
    unit_scale = detect_unit_scale(text)

    is_negative = False
    # Parentheses / brackets denote negative in accounting statements.
    if re.search(r"^\(.*\)$", text) or re.search(r"^\[.*\]$", text):
        is_negative = True
        text = text.strip("()[]")
    # Trailing/leading minus sign.
    if text.startswith("-") or text.endswith("-"):
        is_negative = True

    is_percentage = "%" in text

    # Strip currency symbols/codes and unit-scale words, keep only the
    # numeric core (digits, separators, sign).
    stripped = text
    for sym in _SORTED_SYMBOLS:
        stripped = stripped.replace(sym, "")
    for word in UNIT_SCALE_WORDS:
        stripped = re.sub(re.escape(word), "", stripped, flags=re.IGNORECASE)
    stripped = stripped.replace("%", "").strip()
    stripped = stripped.strip("()[]-").strip()

    # Remove thousands separators (commas or spaces used as separators),
    # keep the decimal point.
    numeric_token = stripped.replace(",", "").replace(" ", "")

    ocr_corrected = False
    if numeric_token and not re.fullmatch(r"[0-9.]*", numeric_token):
        fixed, changed = _fix_ocr_digit_noise(numeric_token)
        if changed:
            numeric_token = fixed
            ocr_corrected = True

    match = re.fullmatch(r"\d*\.?\d*", numeric_token)
    if not numeric_token or not match or numeric_token in {".", ""}:
        return ParsedNumber(
            raw_text=original,
            value=None,
            currency=currency,
            unit_scale=unit_scale,
            is_percentage=is_percentage,
        )

    try:
        value = float(numeric_token)
    except ValueError:
        return ParsedNumber(
            raw_text=original,
            value=None,
            currency=currency,
            unit_scale=unit_scale,
            is_percentage=is_percentage,
        )

    if is_negative:
        value = -abs(value)

    if is_percentage:
        # Preserve as a decimal fraction for calculation convenience while
        # raw_text keeps the literal "9%" for evidence/display purposes.
        value = value / 100.0

    return ParsedNumber(
        raw_text=original,
        value=value,
        currency=currency,
        is_negative=is_negative,
        is_percentage=is_percentage,
        unit_scale=unit_scale,
        ocr_corrected=ocr_corrected,
    )


def approximately_equal(
    actual: Optional[float],
    expected: Optional[float],
    abs_tolerance: float = 0.01,
    rel_tolerance: float = 0.001,
) -> tuple[bool, float]:
    """
    Compare two financial numbers with BOTH an absolute and a relative
    tolerance (see case study section 35).

    Strategy:
        - For small values, absolute tolerance dominates (e.g. invoice
          totals in the tens/hundreds -> 1 cent is meaningful).
        - For large statement totals (millions/crores), a fixed absolute
          cent-level tolerance is meaningless because OCR/rounding noise on
          a nine-figure number can be several rupees; a relative tolerance
          (0.1% by default) is used there instead.
        - The check passes if EITHER tolerance is satisfied.

    Returns (is_within_tolerance, variance) where variance = actual - expected.
    """
    if actual is None or expected is None:
        return False, float("nan")

    variance = actual - expected
    if abs(variance) <= abs_tolerance:
        return True, variance

    denom = max(abs(expected), 1e-9)
    relative = abs(variance) / denom
    if relative <= rel_tolerance:
        return True, variance

    return False, variance


def effective_tolerance(expected: Optional[float], abs_tolerance: float = 0.01,
                         rel_tolerance: float = 0.001) -> float:
    """Return the tolerance value that was effectively allowed for a given
    expected magnitude, for transparency in the validation JSON output."""
    if expected is None:
        return abs_tolerance
    return max(abs_tolerance, abs(expected) * rel_tolerance)
