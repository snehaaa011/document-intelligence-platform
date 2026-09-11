"""

ExtractionProvider abstraction (case study section 6/32):

    ExtractionProvider
        +-- LLMExtractionProvider     (calls Google Gemini through Google's
                                        OpenAI-compatible API endpoint, for
                                        semantic field/table extraction)
        +-- RuleBasedExtractionProvider (deterministic regex/heuristics
                                        fallback -- used automatically when
                                        no LLM_API_KEY / network access is
                                        configured, so the pipeline still
                                        runs end-to-end. This is a REDUCED
                                        QUALITY fallback, not a replacement
                                        for the LLM path -- see README
                                        "Known limitations".)

LLM provider notes:
    This project uses Google's Gemini models via Google's documented
    OpenAI-compatible endpoint:
        https://ai.google.dev/gemini-api/docs/openai
    The official `openai` Python package is used purely as a generic
    OpenAI-protocol REST client, configured with Google's base URL
    (https://generativelanguage.googleapis.com/v1beta/openai/) and a
    Gemini API key. This project does NOT call OpenAI's own API service
    and does NOT require an OpenAI API key anywhere.

IMPORTANT: Neither provider performs financial validation math. They only
extract what is visible. All calculations happen later in
financial_validation_service.py (deterministic Python), per section 34.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.extraction import (
    ExtractionResult,
    InvoiceCanonicalFields,
    InvoiceLineItem,
    EvidenceValue,
    LineItemField,
    PeriodValue,
)
from app.prompts.invoice_prompt import build_invoice_prompt
from app.prompts.balance_sheet_prompt import build_balance_sheet_prompt
from app.prompts.profit_and_loss_prompt import build_profit_and_loss_prompt
from app.prompts.cash_flow_prompt import build_cash_flow_prompt
from app.utils.number_parser import parse_amount, detect_currency, detect_unit_scale

logger = get_logger(__name__)

# Google's documented OpenAI-compatible Gemini endpoint. This is the ONLY
# base URL this provider is allowed to use -- see _build_client() below,
# which refuses to run against OpenAI's own API host as a safety net in
# case of misconfiguration.
OPENAI_API_HOST_BLOCKLIST = ("api.openai.com",)


class ExtractionProviderError(Exception):
    pass


class ExtractionProvider(ABC):
    name: str = "base"

    @abstractmethod
    def extract(self, document_type: str, ocr_text: str, page_count: int) -> ExtractionResult:
        ...


_PROMPT_BUILDERS = {
    "invoice": build_invoice_prompt,
    "balance_sheet": build_balance_sheet_prompt,
    "profit_and_loss": build_profit_and_loss_prompt,
    "cash_flow_statement": build_cash_flow_prompt,
}


class LLMExtractionProvider(ExtractionProvider):
    """
    Calls Google Gemini through Google's OpenAI-compatible API
    (https://ai.google.dev/gemini-api/docs/openai) with a document-type-
    specific prompt and OCR text, requesting strict JSON output, then
    validates/normalizes the response into an ExtractionResult.

    We use the official `openai` Python SDK strictly as an OpenAI-protocol
    HTTP client -- it is pointed at Google's `GEMINI_BASE_URL`
    (https://generativelanguage.googleapis.com/v1beta/openai/), never at
    OpenAI's own API service, and authenticates with `LLM_API_KEY` (a
    Gemini API key from Google AI Studio), never an OpenAI API key.

    Requires network access + LLM_API_KEY at runtime. This class is fully
    implemented and ready to use in a deployed environment; it simply
    cannot be exercised inside a network-isolated sandbox (see README).
    """

    name = "gemini"

    def __init__(self):
        self.settings = get_settings()
        self._client = None  # lazily constructed on first use

    def _get_client(self):
        """Lazily construct the OpenAI-protocol client pointed at Gemini's
        OpenAI-compatible endpoint. Isolated into its own method so a
        missing `openai` package or missing API key fails predictably with
        a controlled ExtractionProviderError rather than crashing the
        whole application at import time."""
        if self._client is not None:
            return self._client

        if not self.settings.LLM_API_KEY:
            raise ExtractionProviderError(
                "LLM_API_KEY is not configured; cannot use LLMExtractionProvider (Gemini)."
            )

        base_url = self.settings.GEMINI_BASE_URL
        if any(blocked in base_url for blocked in OPENAI_API_HOST_BLOCKLIST):
            # Defensive guard: this project must never call OpenAI's own
            # API service, even if GEMINI_BASE_URL is misconfigured.
            raise ExtractionProviderError(
                "GEMINI_BASE_URL is pointed at OpenAI's API host, which this "
                "project must not use. Set it to Google's OpenAI-compatible "
                "Gemini endpoint instead."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ExtractionProviderError(
                "The 'openai' package is not installed. Run "
                "`pip install -r requirements.txt` to install it (it is used "
                "here only as a generic client for Google's Gemini API, not "
                "for OpenAI's own service)."
            ) from exc

        self._client = OpenAI(api_key=self.settings.LLM_API_KEY, base_url=base_url)
        return self._client

    def _call_gemini(self, prompt: str) -> str:
        """Send `prompt` to Gemini via the OpenAI-compatible
        `chat.completions.create` API, requesting JSON-object output, with
        bounded retries and a per-call timeout."""
        client = self._get_client()

        last_exc: Optional[Exception] = None
        for attempt in range(self.settings.LLM_MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=self.settings.LLM_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a precise document-extraction engine. "
                            "You always respond with a single valid JSON object and "
                            "nothing else.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    timeout=self.settings.LLM_TIMEOUT_SECONDS,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:  # pragma: no cover - network dependent
                last_exc = exc
                logger.warning("Gemini call attempt %d failed: %s", attempt + 1, exc)
                if attempt < self.settings.LLM_MAX_RETRIES:
                    time.sleep(min(2 ** attempt, 5))
        raise ExtractionProviderError(f"Gemini extraction failed after retries: {last_exc}")

    def extract(self, document_type: str, ocr_text: str, page_count: int) -> ExtractionResult:
        builder = _PROMPT_BUILDERS.get(document_type)
        if builder is None:
            raise ExtractionProviderError(f"Unsupported document_type: {document_type}")

        prompt = builder(ocr_text, page_count)
        raw_response = self._call_gemini(prompt)

        cleaned = raw_response.strip()
        cleaned = re.sub(r"^```(json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ExtractionProviderError(f"LLM did not return valid JSON: {exc}")

        return _llm_json_to_extraction_result(document_type, parsed)


def _llm_json_to_extraction_result(document_type: str, parsed: dict) -> ExtractionResult:
    """Convert the LLM's raw JSON (matching the prompt schema hints) into
    the strict ExtractionResult pydantic model, tolerating minor shape
    deviations gracefully rather than crashing the whole pipeline."""

    def ev(d) -> Optional[EvidenceValue]:
        if not isinstance(d, dict):
            return None
        raw = d.get("raw_text")
        parsed_num = parse_amount(str(raw)) if raw is not None else None
        return EvidenceValue(
            value=d.get("value") if d.get("value") is not None else (parsed_num.value if parsed_num else None),
            raw_text=raw,
            source_text=d.get("source_text"),
            page_number=d.get("page_number"),
            currency=d.get("currency"),
            unit_scale=d.get("unit_scale"),
        )

    result = ExtractionResult(document_type=document_type, provider_name="gemini")

    if document_type == "invoice":
        cf = parsed.get("canonical_fields", {})
        result.invoice_fields = InvoiceCanonicalFields(
            invoice_number=ev(cf.get("invoice_number")),
            invoice_date=ev(cf.get("invoice_date")),
            due_date=ev(cf.get("due_date")),
            vendor_name=cf.get("vendor_name"),
            vendor_address=cf.get("vendor_address"),
            vendor_tax_id=cf.get("vendor_tax_id"),
            customer_name=cf.get("customer_name"),
            billing_address=cf.get("billing_address"),
            shipping_address=cf.get("shipping_address"),
            customer_tax_id=cf.get("customer_tax_id"),
            purchase_order=cf.get("purchase_order"),
            payment_terms=cf.get("payment_terms"),
            salesperson=cf.get("salesperson"),
            currency=cf.get("currency"),
            subtotal=ev(cf.get("subtotal")),
            discount_amount=ev(cf.get("discount_amount")),
            tax_amount=ev(cf.get("tax_amount")),
            shipping_amount=ev(cf.get("shipping_amount")),
            total_amount=ev(cf.get("total_amount")),
            amount_paid=ev(cf.get("amount_paid")),
            amount_due=ev(cf.get("amount_due")),
            cash_tendered=ev(cf.get("cash_tendered")),
            change_returned=ev(cf.get("change_returned")),
            tax_inclusive=cf.get("tax_inclusive"),
        )
        for li in parsed.get("line_items", []):
            result.invoice_line_items.append(
                InvoiceLineItem(
                    description=li.get("description"),
                    hsn_sac=li.get("hsn_sac"),
                    quantity=ev(li.get("quantity")),
                    unit=li.get("unit"),
                    unit_price=ev(li.get("unit_price")),
                    discount_percent=ev(li.get("discount_percent")),
                    tax_rate=ev(li.get("tax_rate")),
                    line_total=ev(li.get("line_total")),
                    page_number=li.get("page_number"),
                )
            )
    else:
        meta = parsed.get("statement_meta", {})
        result.notes.append(f"statement_title={meta.get('statement_title')}")
        for li in parsed.get("line_items", []):
            periods = []
            for p in li.get("periods", []):
                evv = ev(p)
                if evv is None:
                    evv = EvidenceValue()
                periods.append(PeriodValue(label=p.get("label", ""), evidence=evv))
            result.statement_line_items.append(
                LineItemField(
                    field_name=li.get("field_name", ""),
                    canonical_name=li.get("canonical_name"),
                    periods=periods,
                    schedule_reference=li.get("schedule_reference"),
                    page_number=li.get("page_number"),
                    section=li.get("section"),
                )
            )
        result.periods = parsed.get("periods", [])

    result.additional_fields = parsed.get("additional_fields", {}) or {}
    result.notes.extend(parsed.get("notes", []) or [])
    return result


# ---------------------------------------------------------------------------
# Rule-based fallback provider
# ---------------------------------------------------------------------------
class RuleBasedExtractionProvider(ExtractionProvider):
    """
    Deterministic regex/heuristic extractor used automatically when no LLM
    is configured (no network / no API key), so the pipeline still runs
    end-to-end offline. This intentionally trades semantic completeness
    for zero external dependencies -- see README "Known limitations" for
    an honest comparison against the LLM path.
    """

    name = "rule_based"

    def extract(self, document_type: str, ocr_text: str, page_count: int) -> ExtractionResult:
        if document_type == "invoice":
            return self._extract_invoice(ocr_text)
        return self._extract_statement(document_type, ocr_text)

    # -- Invoice heuristics ------------------------------------------------
    _LABEL_PATTERNS = {
        "invoice_number": r"(?:invoice\s*no\.?|invoice\s*#|bill\s*no\.?|trn)\s*[:\-]?\s*([A-Za-z0-9\-/]{3,})",
        "invoice_date": r"(?:invoice\s*date|dated|date)\s*[:\-]?\s*([0-9]{1,2}[\-/][A-Za-z0-9]{2,9}[\-/][0-9]{2,4})",
        "due_date": r"due\s*date\s*[:\-]?\s*([0-9]{1,2}[\-/][A-Za-z0-9]{2,9}[\-/][0-9]{2,4})",
        "purchase_order": r"(?:buyer'?s\s*order\s*no\.?|purchase\s*order|p\.?o\.?\s*no\.?)\s*[:\-]?\s*([A-Za-z0-9\-/]{2,})",
        "vendor_tax_id": r"GSTIN[/\\]?UIN\s*[:\-]?\s*([0-9A-Z]{10,15})",
    }

    _TOTAL_PATTERNS = {
        "total_amount": r"(?:grand\s*total|amount\s*chargeable|total\s*amount\s*due|total\s+includes\s+gst\s*\d*%?|^total)\D{0,20}([₹$]?\s?[\d,]+\.\d{2})",
        "subtotal": r"(?:sub\s*-?\s*total|taxable\s*value)\D{0,10}([₹$]?\s?[\d,]+\.\d{2})",
        "tax_amount": r"(?:total\s*tax\s*amount|gst\s*amount|tax\s*amount)\D{0,10}([₹$]?\s?[\d,]+\.\d{2})",
        "cash_tendered": r"\bcash\b\D{0,10}([\d,]+\.\d{2})",
        "change_returned": r"\bchange\b\D{0,10}([\d,]+\.\d{2})",
    }

    def _extract_invoice(self, text: str) -> ExtractionResult:
        result = ExtractionResult(document_type="invoice", provider_name=self.name)
        flat = text

        fields = {}
        for key, pattern in self._LABEL_PATTERNS.items():
            m = re.search(pattern, flat, re.IGNORECASE)
            fields[key] = m.group(1).strip() if m else None

        evidence_fields = {}
        for key, pattern in self._TOTAL_PATTERNS.items():
            m = re.search(pattern, flat, re.IGNORECASE | re.MULTILINE)
            if m:
                parsed_num = parse_amount(m.group(1))
                evidence_fields[key] = EvidenceValue(
                    value=parsed_num.value,
                    raw_text=m.group(1),
                    source_text=m.group(0),
                    currency=parsed_num.currency or detect_currency(flat),
                )
            else:
                evidence_fields[key] = None

        currency = detect_currency(flat)
        tax_inclusive = bool(re.search(r"total\s+includes\s+gst", flat, re.IGNORECASE))

        # Vendor name heuristic: first non-empty line that isn't a generic
        # heading like "TAX INVOICE" / "RECEIPT".
        vendor_name = None
        for line in flat.splitlines():
            clean = line.strip()
            if not clean:
                continue
            if re.fullmatch(r"(TAX\s*INVOICE|INVOICE|RECEIPT|BILL)\.?", clean, re.IGNORECASE):
                continue
            vendor_name = clean
            break

        result.invoice_fields = InvoiceCanonicalFields(
            invoice_number=EvidenceValue(value=None, raw_text=fields.get("invoice_number")) if fields.get("invoice_number") else None,
            invoice_date=EvidenceValue(value=None, raw_text=fields.get("invoice_date")) if fields.get("invoice_date") else None,
            due_date=EvidenceValue(value=None, raw_text=fields.get("due_date")) if fields.get("due_date") else None,
            vendor_name=vendor_name,
            vendor_tax_id=fields.get("vendor_tax_id"),
            purchase_order=fields.get("purchase_order"),
            currency=currency,
            subtotal=evidence_fields.get("subtotal"),
            tax_amount=evidence_fields.get("tax_amount"),
            total_amount=evidence_fields.get("total_amount"),
            cash_tendered=evidence_fields.get("cash_tendered"),
            change_returned=evidence_fields.get("change_returned"),
            tax_inclusive=tax_inclusive or None,
        )

        result.extraction_warnings.append(
            "Extracted using the deterministic rule-based fallback provider "
            "(no LLM configured). Field coverage is intentionally reduced "
            "compared to the LLM extraction path -- line items and several "
            "address/reference fields are not populated by this fallback."
        )
        return result

    # -- Financial statement heuristics -------------------------------------
    _TRAILING_NUMBERS = re.compile(
        r"(\(?-?[₹$]?\s?[\d][\d,]*\.\d{1,2}\)?)\s*$"
    )
    _TWO_TRAILING_NUMBERS = re.compile(
        r"(\(?-?[₹$]?\s?[\d][\d,]*\.\d{1,2}\)?)\s+(\(?-?[₹$]?\s?[\d][\d,]*\.\d{1,2}\)?)\s*$"
    )
    _PERIOD_HEADER = re.compile(
        r"(As at|Year ended)\s+([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{1,2}[\-/][A-Za-z]{3}[\-/]\d{2,4})",
        re.IGNORECASE,
    )

    def _extract_statement(self, document_type: str, text: str) -> ExtractionResult:
        result = ExtractionResult(document_type=document_type, provider_name=self.name)

        currency = detect_currency(text) or "INR"
        unit_scale = detect_unit_scale(text)

        period_labels = [f"{m.group(1)} {m.group(2)}" for m in self._PERIOD_HEADER.finditer(text)]
        # De-duplicate while preserving order.
        seen = set()
        unique_periods = []
        for p in period_labels:
            if p not in seen:
                seen.add(p)
                unique_periods.append(p)
        result.periods = unique_periods[:2] if unique_periods else []

        current_section = None
        section_headers = {
            "CAPITAL AND LIABILITIES": "CAPITAL AND LIABILITIES",
            "ASSETS": "ASSETS",
            "INCOME": "INCOME",
            "EXPENDITURE": "EXPENDITURE",
            "PROFIT": "PROFIT",
            "APPROPRIATIONS": "APPROPRIATIONS",
            "CASH FLOWS FROM OPERATING": "OPERATING ACTIVITIES",
            "CASH FLOWS FROM INVESTING": "INVESTING ACTIVITIES",
            "CASH FLOWS FROM FINANCING": "FINANCING ACTIVITIES",
        }

        line_items = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # OCR sometimes splits a decimal point from its integer part
            # with a stray space (e.g. "2,709,921 .85"); merge it back so
            # the trailing-number regexes below can match it as one token.
            line = re.sub(r"(\d)\s+\.(\d)", r"\1.\2", line)

            upper = line.upper()
            for header_key, section_name in section_headers.items():
                if header_key in upper:
                    current_section = section_name
                    break

            match2 = self._TWO_TRAILING_NUMBERS.search(line)
            match1 = None if match2 else self._TRAILING_NUMBERS.search(line)
            if not match2 and not match1:
                continue

            if match2:
                label = line[: match2.start()].strip(" .:-")
                values_raw = [match2.group(1), match2.group(2)]
            else:
                label = line[: match1.start()].strip(" .:-")
                values_raw = [match1.group(1)]

            # Strip a leading schedule/note number token from the label if present.
            label = re.sub(r"^\d+\s+", "", label)

            # Strip a trailing schedule/note number token from the label if present.
            label = re.sub(r"\s+\d+$", "", label)

            # Strip a trailing OCR-misread schedule-column artifact: a
            # short (<=3 char) alphanumeric token stuck to the end of the
            # label just before the numeric columns (e.g. "... India OD",
            # "... short notice N", "Advances o"), but only when the
            # preceding text already forms a plausible multi-word label so
            # we never eat a real short label like "Total".
            words_in_label = label.split()
            if len(words_in_label) >= 3 and re.fullmatch(r"[A-Za-z=()0-9]{1,3}", words_in_label[-1]):
                label = " ".join(words_in_label[:-1])
            if not label or len(label) < 3 or label.isdigit():
                continue
            if re.fullmatch(r"(schedule|as at|year ended).*", label, re.IGNORECASE):
                continue

            periods = []
            for idx, raw_val in enumerate(values_raw):
                parsed_num = parse_amount(raw_val, assume_currency=currency)
                if parsed_num.value is None:
                    continue
                label_period = (
                    result.periods[idx] if idx < len(result.periods) else f"period_{idx+1}"
                )
                periods.append(
                    PeriodValue(
                        label=label_period,
                        evidence=EvidenceValue(
                            value=parsed_num.value,
                            raw_text=raw_val,
                            source_text=line,
                            currency=currency,
                            unit_scale=unit_scale,
                        ),
                    )
                )
            if not periods:
                continue

            canonical = None
            lbl_lower = label.lower()
            line_section = current_section
            if lbl_lower == "total" and current_section == "ASSETS":
                canonical = "total_assets"
                # A balance sheet's memorandum items (for example,
                # "Contingent liabilities" and "Bills for collection")
                # appear after Total Assets. They are not asset components,
                # so stop carrying the ASSETS section forward.
                current_section = None
            elif lbl_lower == "total" and current_section == "CAPITAL AND LIABILITIES":
                canonical = "total_capital_and_liabilities"
            elif "net cash flow" in lbl_lower and "operating" in lbl_lower:
                canonical = "net_cash_from_operating_activities"
            elif "net cash flow" in lbl_lower and "investing" in lbl_lower:
                canonical = "net_cash_from_investing_activities"
            elif "net cash flow" in lbl_lower and "financing" in lbl_lower:
                canonical = "net_cash_from_financing_activities"
            elif "beginning of the year" in lbl_lower or "beginning of period" in lbl_lower:
                canonical = "opening_cash_and_equivalents"
            elif "end of the year" in lbl_lower or "end of period" in lbl_lower:
                canonical = "closing_cash_and_equivalents"
            elif "before minority interest" in lbl_lower:
                canonical = "net_profit_before_minority_interest"
            elif lbl_lower == "minority interest" and current_section == "PROFIT":
                canonical = "minority_interest"
            elif "attributable to the group" in lbl_lower:
                canonical = "net_profit_attributable_to_group"
            elif lbl_lower == "total" and current_section == "INCOME":
                canonical = "total_income"
            elif lbl_lower == "total" and current_section == "EXPENDITURE":
                canonical = "total_expenditure"
            elif lbl_lower == "basic":
                canonical = "earnings_per_share_basic"
            elif lbl_lower == "diluted":
                canonical = "earnings_per_share_diluted"

            line_items.append(
                LineItemField(
                    field_name=label,
                    canonical_name=canonical,
                    periods=periods,
                    section=line_section,
                )
            )

        result.statement_line_items = line_items
        result.extraction_warnings.append(
            "Extracted using the deterministic rule-based fallback provider "
            "(no LLM configured). Line-item labels/sections are inferred "
            "from OCR text layout heuristics and may miss items with "
            "unusual formatting -- the LLM extraction path is recommended "
            "for production use."
        )
        return result


def get_extraction_provider() -> ExtractionProvider:
    """
    Provider selection logic (case study "Configuration" requirements):

        LLM_PROVIDER=gemini   + valid LLM_API_KEY           -> Gemini LLM extraction
        LLM_PROVIDER=gemini   + missing LLM_API_KEY         -> safe fallback to rule_based
        LLM_PROVIDER=gemini   + `openai` package unavailable -> safe fallback to rule_based
        LLM_PROVIDER=rule_based (or anything else)          -> RuleBasedExtractionProvider

    This function never raises -- a misconfigured LLM provider must
    degrade to the offline fallback, not crash the application.
    """
    settings = get_settings()

    if settings.LLM_PROVIDER == "gemini":
        if not settings.LLM_API_KEY:
            logger.warning(
                "LLM_PROVIDER=gemini but LLM_API_KEY is empty; "
                "falling back to RuleBasedExtractionProvider."
            )
            return RuleBasedExtractionProvider()
        try:
            import openai  # noqa: F401  (import check only)
        except ImportError:
            logger.warning(
                "LLM_PROVIDER=gemini but the 'openai' package is not installed; "
                "falling back to RuleBasedExtractionProvider. Run "
                "`pip install -r requirements.txt` to enable Gemini extraction."
            )
            return RuleBasedExtractionProvider()
        return LLMExtractionProvider()

    if settings.LLM_PROVIDER != "rule_based":
        logger.warning(
            "Unknown LLM_PROVIDER=%s; falling back to RuleBasedExtractionProvider. "
            "Supported values are 'gemini' and 'rule_based'.",
            settings.LLM_PROVIDER,
        )
    return RuleBasedExtractionProvider()


def get_effective_provider_name() -> str:
    """Returns the provider name that get_extraction_provider() would
    actually select right now (post-fallback), used by the health endpoint
    so it never reports a provider that isn't really active."""
    return get_extraction_provider().name
