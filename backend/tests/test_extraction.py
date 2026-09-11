"""
tests/test_extraction.py

Covers case study section 37 (extraction-related items) using the
deterministic rule-based provider so tests run with zero external
dependencies / no API key (section 37: "Do not require a paid API just to
run unit tests"). The Gemini LLM provider path is exercised entirely via
a mocked OpenAI-compatible client (`LLMExtractionProvider._get_client` is
monkeypatched to return a `MagicMock`) -- no real Gemini API key, network
access, or the actual `openai` package internals are required for these
tests to pass.
"""
import json
from unittest.mock import MagicMock

import pytest

from app.providers.extraction_providers import (
    RuleBasedExtractionProvider,
    LLMExtractionProvider,
    ExtractionProviderError,
    get_extraction_provider,
    get_effective_provider_name,
)
from app.core.config import get_settings


SAMPLE_INVOICE_TEXT = """
Shankar Enterprises-(2023-24)
TAX INVOICE
Invoice No. SCI/25-26/3331
Dated 16-Jul-25
GSTIN/UIN 19BFJPK5651N1ZS
5,815.17
SGST@9% 523.36
CGST@9% 523.36
Total Amount Chargeable ₹ 6,862.00
"""

SAMPLE_BALANCE_SHEET_TEXT = """
CONSOLIDATED BALANCE SHEET
As at March 31, 2026 As at March 31, 2025
CAPITAL AND LIABILITIES
Capital 1 1,539.34 765.22
Deposits 3 3,099,638.29 2,710,898.23
Total 4,908,040.84 4,392,417.42
ASSETS
Cash and balances with Reserve Bank of India 6 200,707.11 144,390.25
Total 4,908,040.84 4,392,417.42
"""


def _mock_client(responses):
    """Builds a MagicMock shaped like the OpenAI SDK client so
    `client.chat.completions.create(...)` behaves as configured, without
    depending on the real `openai` package's internal class layout.

    `responses` may be:
        - a single JSON string -> every call returns that content
        - a list of items, each either a string (success) or an Exception
          instance (raised on that call) -- consumed in order, useful for
          testing retry behavior.
    """
    client = MagicMock()
    client.base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

    def _make_response(content: str):
        message = MagicMock()
        message.content = content
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    if isinstance(responses, str):
        client.chat.completions.create.return_value = _make_response(responses)
    else:
        side_effects = [
            item if isinstance(item, Exception) else _make_response(item)
            for item in responses
        ]
        client.chat.completions.create.side_effect = side_effects

    return client


# ---------------------------------------------------------------------------
# Rule-based provider (offline, no API key required)
# ---------------------------------------------------------------------------
def test_rule_based_invoice_extraction_finds_totals():
    provider = RuleBasedExtractionProvider()
    result = provider.extract("invoice", SAMPLE_INVOICE_TEXT, page_count=1)
    assert result.invoice_fields is not None
    assert result.invoice_fields.total_amount is not None
    assert result.invoice_fields.total_amount.value == 6862.00
    assert result.invoice_fields.vendor_tax_id == "19BFJPK5651N1ZS"
    assert len(result.extraction_warnings) > 0


def test_rule_based_balance_sheet_extraction_finds_totals():
    provider = RuleBasedExtractionProvider()
    result = provider.extract("balance_sheet", SAMPLE_BALANCE_SHEET_TEXT, page_count=1)
    field_names = {item.field_name: item for item in result.statement_line_items}
    assert "Deposits" in field_names
    deposits = field_names["Deposits"]
    values = [p.evidence.value for p in deposits.periods]
    assert 3099638.29 in values


def test_rule_based_never_raises_on_garbage_input():
    provider = RuleBasedExtractionProvider()
    result = provider.extract("invoice", "asdkjfh 8ashdf @@@ !!!! \n\n", page_count=1)
    assert result.invoice_fields is not None  # returns nulls, not an exception


# ---------------------------------------------------------------------------
# Provider selection (case study "Configuration" requirements)
# ---------------------------------------------------------------------------
def test_provider_selection_rule_based_when_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "rule_based")
    provider = get_extraction_provider()
    assert isinstance(provider, RuleBasedExtractionProvider)
    assert get_effective_provider_name() == "rule_based"


def test_provider_selection_gemini_when_key_present(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "LLM_API_KEY", "fake-gemini-key")
    provider = get_extraction_provider()
    assert isinstance(provider, LLMExtractionProvider)
    assert provider.name == "gemini"


def test_provider_selection_falls_back_when_gemini_key_missing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    provider = get_extraction_provider()
    assert isinstance(provider, RuleBasedExtractionProvider)
    assert get_effective_provider_name() == "rule_based"


def test_provider_selection_unknown_value_falls_back(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "some_unsupported_provider")
    provider = get_extraction_provider()
    assert isinstance(provider, RuleBasedExtractionProvider)


# ---------------------------------------------------------------------------
# Gemini provider (mocked -- no real API key/network used)
# ---------------------------------------------------------------------------
def test_gemini_provider_requires_api_key(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "")
    with pytest.raises(ExtractionProviderError):
        provider.extract("invoice", "some text", 1)


def test_gemini_provider_refuses_openai_host(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "fake-key")
    monkeypatch.setattr(provider.settings, "GEMINI_BASE_URL", "https://api.openai.com/v1")
    with pytest.raises(ExtractionProviderError):
        provider._get_client()


def test_gemini_provider_builds_client_with_gemini_base_url(monkeypatch):
    """Verifies the client is constructed with Google's Gemini
    OpenAI-compatible base URL, never OpenAI's own API host, WITHOUT
    requiring the real `openai` package to be importable in this
    environment: we monkeypatch the module-level `OpenAI` symbol that
    `_get_client` imports lazily."""
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "fake-key")

    captured = {}

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    import sys
    import types

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    provider._get_client()
    assert captured["api_key"] == "fake-key"
    assert "generativelanguage.googleapis.com" in captured["base_url"]
    assert "api.openai.com" not in captured["base_url"]


def test_gemini_provider_parses_mocked_invoice_response(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    provider._client = _mock_client(
        json.dumps(
            {
                "canonical_fields": {
                    "invoice_number": {"value": None, "raw_text": "INV-001", "source_text": "Invoice No INV-001"},
                    "total_amount": {"value": 100.0, "raw_text": "100.00", "source_text": "Total 100.00"},
                },
                "line_items": [],
                "additional_fields": {},
                "periods": [],
                "notes": [],
            }
        )
    )
    result = provider.extract("invoice", "irrelevant OCR text", 1)
    assert result.provider_name == "gemini"
    assert result.invoice_fields.total_amount.value == 100.0
    assert result.invoice_fields.invoice_number.raw_text == "INV-001"


def test_gemini_provider_parses_mocked_balance_sheet_response(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    provider._client = _mock_client(
        json.dumps(
            {
                "statement_meta": {"currency": "INR", "unit_scale": "crore"},
                "line_items": [
                    {
                        "field_name": "Deposits",
                        "canonical_name": None,
                        "section": "CAPITAL AND LIABILITIES",
                        "periods": [
                            {"label": "31-Mar-2026", "value": 3099638.29, "raw_text": "3,099,638.29"},
                            {"label": "31-Mar-2025", "value": 2710898.23, "raw_text": "2,710,898.23"},
                        ],
                    }
                ],
                "additional_fields": {},
                "periods": ["31-Mar-2026", "31-Mar-2025"],
                "notes": [],
            }
        )
    )
    result = provider.extract("balance_sheet", "irrelevant OCR text", 1)
    assert result.statement_line_items[0].field_name == "Deposits"
    assert result.statement_line_items[0].periods[0].evidence.value == 3099638.29


def test_gemini_provider_parses_mocked_profit_and_loss_response(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    provider._client = _mock_client(
        json.dumps(
            {
                "statement_meta": {"currency": "INR", "unit_scale": "crore"},
                "line_items": [
                    {
                        "field_name": "Total", "canonical_name": "total_income", "section": "INCOME",
                        "periods": [{"label": "Year ended March 31, 2026", "value": 495462.81, "raw_text": "495,462.81"}],
                    }
                ],
                "additional_fields": {}, "periods": ["Year ended March 31, 2026"], "notes": [],
            }
        )
    )
    result = provider.extract("profit_and_loss", "irrelevant OCR text", 1)
    assert result.statement_line_items[0].canonical_name == "total_income"


def test_gemini_provider_parses_mocked_cash_flow_response(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    provider._client = _mock_client(
        json.dumps(
            {
                "statement_meta": {"currency": "INR", "unit_scale": "crore"},
                "line_items": [
                    {
                        "field_name": "Net cash flows from operating activities",
                        "canonical_name": "net_cash_from_operating_activities", "section": "OPERATING",
                        "periods": [{"label": "Year ended March 31, 2026", "value": 113506.38, "raw_text": "113,506.38"}],
                    }
                ],
                "additional_fields": {}, "periods": ["Year ended March 31, 2026"], "notes": [],
            }
        )
    )
    result = provider.extract("cash_flow_statement", "irrelevant OCR text", 1)
    assert result.statement_line_items[0].canonical_name == "net_cash_from_operating_activities"


def test_gemini_provider_handles_malformed_json(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    provider._client = _mock_client("this is not valid json {{{")
    with pytest.raises(ExtractionProviderError):
        provider.extract("invoice", "irrelevant OCR text", 1)


def test_gemini_provider_handles_markdown_fenced_json(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    provider._client = _mock_client(
        "```json\n" + json.dumps({
            "canonical_fields": {"total_amount": {"value": 50.0, "raw_text": "50.00", "source_text": "Total 50.00"}},
            "line_items": [], "additional_fields": {}, "periods": [], "notes": [],
        }) + "\n```"
    )
    result = provider.extract("invoice", "irrelevant OCR text", 1)
    assert result.invoice_fields.total_amount.value == 50.0


def test_gemini_provider_retries_then_raises_on_persistent_api_error(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(provider.settings, "LLM_MAX_RETRIES", 1)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = _mock_client([TimeoutError("simulated timeout"), TimeoutError("simulated timeout")])
    provider._client = client
    with pytest.raises(ExtractionProviderError):
        provider.extract("invoice", "irrelevant OCR text", 1)
    assert client.chat.completions.create.call_count == 2  # 1 initial + 1 retry


def test_gemini_provider_succeeds_after_transient_failure(monkeypatch):
    provider = LLMExtractionProvider()
    monkeypatch.setattr(provider.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(provider.settings, "LLM_MAX_RETRIES", 2)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    good_json = json.dumps({
        "canonical_fields": {"total_amount": {"value": 20.0, "raw_text": "20.00", "source_text": "Total 20.00"}},
        "line_items": [], "additional_fields": {}, "periods": [], "notes": [],
    })
    client = _mock_client([ConnectionError("transient"), good_json])
    provider._client = client
    result = provider.extract("invoice", "irrelevant OCR text", 1)
    assert result.invoice_fields.total_amount.value == 20.0
    assert client.chat.completions.create.call_count == 2
