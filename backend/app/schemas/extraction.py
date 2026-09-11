"""
schemas/extraction.py

Pydantic models describing the STRUCTURED OUTPUT contract that every
extraction provider (LLM-based or rule-based) must satisfy, and that the
financial validation engine consumes.

Design principles (case study sections 4, 5, 9, 12, 13):
    - Hybrid schema: canonical_fields (well-known accounting concepts) +
      additional_fields (anything else visible) + line_items + periods.
    - Every leaf value is an EvidenceValue: {value, raw_text, source_text,
      page_number, unit_scale, currency} so we never lose provenance and
      never silently coerce "not visible" into a fabricated number.
    - Nothing here performs calculations. This module is data-only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceValue(BaseModel):
    """A single extracted scalar with provenance, per case study section 13."""

    value: Optional[float] = None
    raw_text: Optional[str] = Field(
        default=None, description="The literal displayed text, e.g. '(1,234.50)'"
    )
    source_text: Optional[str] = Field(
        default=None, description="Surrounding text/line the value was read from"
    )
    page_number: Optional[int] = None
    currency: Optional[str] = None
    unit_scale: Optional[str] = Field(
        default=None, description="'crore' | 'lakh' | 'thousand' | 'million' | None"
    )
    is_percentage: bool = False
    confidence: Optional[float] = None


class PeriodValue(BaseModel):
    """One comparative-period observation of a line item (section 12)."""

    label: str = Field(..., description="e.g. '31-Mar-2026', '2025-03-31', 'Year ended March 31, 2026'")
    evidence: EvidenceValue


class LineItemField(BaseModel):
    """A single financial-statement line item, potentially with several
    comparative periods (section 9 example: 'Deposits' with 2026/2025)."""

    field_name: str = Field(..., description="Original source label, verbatim")
    canonical_name: Optional[str] = Field(
        default=None, description="Well-known equivalent, e.g. 'total_assets', when applicable"
    )
    periods: List[PeriodValue] = Field(default_factory=list)
    schedule_reference: Optional[str] = None
    page_number: Optional[int] = None
    section: Optional[str] = Field(
        default=None, description="e.g. 'CAPITAL AND LIABILITIES', 'ASSETS', 'INCOME'"
    )


class InvoiceLineItem(BaseModel):
    """A single invoice/receipt table row."""

    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    quantity: Optional[EvidenceValue] = None
    unit: Optional[str] = None
    unit_price: Optional[EvidenceValue] = None
    discount_percent: Optional[EvidenceValue] = None
    tax_rate: Optional[EvidenceValue] = None
    line_total: Optional[EvidenceValue] = None
    page_number: Optional[int] = None


class InvoiceCanonicalFields(BaseModel):
    invoice_number: Optional[EvidenceValue] = None
    invoice_date: Optional[EvidenceValue] = None
    due_date: Optional[EvidenceValue] = None
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    customer_name: Optional[str] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    customer_tax_id: Optional[str] = None
    purchase_order: Optional[str] = None
    payment_terms: Optional[str] = None
    salesperson: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[EvidenceValue] = None
    discount_amount: Optional[EvidenceValue] = None
    tax_amount: Optional[EvidenceValue] = None
    shipping_amount: Optional[EvidenceValue] = None
    total_amount: Optional[EvidenceValue] = None
    amount_paid: Optional[EvidenceValue] = None
    amount_due: Optional[EvidenceValue] = None
    cash_tendered: Optional[EvidenceValue] = None
    change_returned: Optional[EvidenceValue] = None
    tax_inclusive: Optional[bool] = Field(
        default=None, description="True if totals/line amounts already include tax"
    )


class FinancialStatementCanonicalFields(BaseModel):
    """Loose canonical anchors shared across balance sheet / P&L / cash
    flow. Every field is optional; absence simply means the statement did
    not surface a semantically equivalent line under a recognizable label.
    """

    statement_title: Optional[str] = None
    entity_name: Optional[str] = None
    reporting_period_end: Optional[str] = None
    comparative_period_end: Optional[str] = None
    currency: Optional[str] = None
    unit_scale: Optional[str] = None

    total_assets: Optional[LineItemField] = None
    total_capital_and_liabilities: Optional[LineItemField] = None
    total_income: Optional[LineItemField] = None
    total_expenditure: Optional[LineItemField] = None
    net_profit_before_minority_interest: Optional[LineItemField] = None
    minority_interest: Optional[LineItemField] = None
    net_profit_attributable_to_group: Optional[LineItemField] = None
    earnings_per_share_basic: Optional[LineItemField] = None
    earnings_per_share_diluted: Optional[LineItemField] = None

    net_cash_from_operating_activities: Optional[LineItemField] = None
    net_cash_from_investing_activities: Optional[LineItemField] = None
    net_cash_from_financing_activities: Optional[LineItemField] = None
    net_increase_in_cash: Optional[LineItemField] = None
    opening_cash_and_equivalents: Optional[LineItemField] = None
    closing_cash_and_equivalents: Optional[LineItemField] = None


class ExtractionResult(BaseModel):
    """
    Top-level structured extraction envelope returned by ANY provider
    (LLM-based or rule-based) for ANY of the four document types.

    Only one of `invoice_fields` / `statement_fields` will be populated,
    matching the supplied document_type.
    """

    document_type: str
    canonical_fields_present: bool = False

    invoice_fields: Optional[InvoiceCanonicalFields] = None
    invoice_line_items: List[InvoiceLineItem] = Field(default_factory=list)

    statement_fields: Optional[FinancialStatementCanonicalFields] = None
    statement_line_items: List[LineItemField] = Field(default_factory=list)

    additional_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="Anything meaningful that doesn't fit the canonical shape "
        "above, keyed by the original source label.",
    )
    periods: List[str] = Field(
        default_factory=list, description="Distinct period labels seen in the document"
    )
    notes: List[str] = Field(default_factory=list)
    extraction_warnings: List[str] = Field(default_factory=list)
    ocr_used: bool = False
    provider_name: Optional[str] = None
