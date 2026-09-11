"""
tests/test_validation.py

Covers case study section 37 items 8-12: invoice, balance sheet, P&L,
cash flow validation, and NOT_APPLICABLE handling. Uses hand-built
ExtractionResult fixtures rather than real OCR so the validation MATH is
tested in isolation from OCR/LLM variability.
"""
from app.schemas.extraction import (
    ExtractionResult,
    InvoiceCanonicalFields,
    InvoiceLineItem,
    EvidenceValue,
    LineItemField,
    PeriodValue,
)
from app.services.financial_validation_service import (
    validate_invoice,
    validate_balance_sheet,
    validate_profit_and_loss,
    validate_cash_flow,
)


def ev(value):
    return EvidenceValue(value=value, raw_text=str(value) if value is not None else None)


# --- Invoice ----------------------------------------------------------------
def test_invoice_validation_all_pass():
    extraction = ExtractionResult(
        document_type="invoice",
        invoice_fields=InvoiceCanonicalFields(
            subtotal=ev(100.0),
            tax_amount=ev(18.0),
            total_amount=ev(118.0),
            tax_inclusive=False,
        ),
        invoice_line_items=[
            InvoiceLineItem(quantity=ev(2), unit_price=ev(50.0), line_total=ev(100.0)),
        ],
    )
    result = validate_invoice(extraction)
    assert result.overall_status == "PASS"
    for check in result.checks:
        assert check.status in ("PASS", "NOT_APPLICABLE")


def test_invoice_validation_detects_mismatch():
    extraction = ExtractionResult(
        document_type="invoice",
        invoice_fields=InvoiceCanonicalFields(
            subtotal=ev(100.0),
            tax_amount=ev(18.0),
            total_amount=ev(500.0),  # deliberately wrong
            tax_inclusive=False,
        ),
    )
    result = validate_invoice(extraction)
    assert result.overall_status == "FAIL"
    failing = [c for c in result.checks if c.name == "taxable_amount_plus_tax_vs_total"]
    assert failing[0].status == "FAIL"


def test_invoice_validation_cash_change():
    extraction = ExtractionResult(
        document_type="invoice",
        invoice_fields=InvoiceCanonicalFields(
            total_amount=ev(9.0),
            cash_tendered=ev(50.0),
            change_returned=ev(41.0),
            tax_inclusive=True,
        ),
    )
    result = validate_invoice(extraction)
    cash_check = [c for c in result.checks if c.name == "cash_minus_total_vs_change"][0]
    assert cash_check.status == "PASS"


def test_invoice_validation_not_applicable_when_missing():
    extraction = ExtractionResult(document_type="invoice", invoice_fields=InvoiceCanonicalFields())
    result = validate_invoice(extraction)
    assert all(c.status == "NOT_APPLICABLE" for c in result.checks)
    assert result.overall_status == "NOT_APPLICABLE"


# --- Balance sheet ------------------------------------------------------------
def _balance_sheet_extraction(assets_val=100.0, cl_val=100.0, component_sum=None):
    periods = ["31-Mar-2026"]
    total_assets = LineItemField(
        field_name="Total", canonical_name="total_assets", section="ASSETS",
        periods=[PeriodValue(label="31-Mar-2026", evidence=ev(assets_val))],
    )
    total_cl = LineItemField(
        field_name="Total", canonical_name="total_capital_and_liabilities", section="CAPITAL AND LIABILITIES",
        periods=[PeriodValue(label="31-Mar-2026", evidence=ev(cl_val))],
    )
    items = [total_assets, total_cl]
    if component_sum is not None:
        for i, val in enumerate(component_sum):
            items.append(
                LineItemField(
                    field_name=f"Asset component {i}", section="ASSETS",
                    periods=[PeriodValue(label="31-Mar-2026", evidence=ev(val))],
                )
            )
    return ExtractionResult(document_type="balance_sheet", statement_line_items=items, periods=periods)


def test_balance_sheet_totals_match():
    extraction = _balance_sheet_extraction(100.0, 100.0)
    result = validate_balance_sheet(extraction)
    main_check = [c for c in result.checks if c.name == "total_capital_liabilities_vs_total_assets"][0]
    assert main_check.status == "PASS"


def test_balance_sheet_totals_mismatch_fails():
    extraction = _balance_sheet_extraction(100.0, 90.0)
    result = validate_balance_sheet(extraction)
    assert result.overall_status == "FAIL"


def test_balance_sheet_component_sum_reconciles():
    extraction = _balance_sheet_extraction(100.0, 100.0, component_sum=[60.0, 40.0])
    result = validate_balance_sheet(extraction)
    comp_check = [c for c in result.checks if c.name == "sum_of_asset_components_vs_reported_total"][0]
    assert comp_check.status == "PASS"


# --- Profit & loss --------------------------------------------------------------
def test_profit_and_loss_reconciles():
    periods = ["Year ended March 31, 2026"]
    items = [
        LineItemField(field_name="Total", canonical_name="total_income",
                      periods=[PeriodValue(label=periods[0], evidence=ev(500.0))]),
        LineItemField(field_name="Total", canonical_name="total_expenditure",
                      periods=[PeriodValue(label=periods[0], evidence=ev(400.0))]),
        LineItemField(field_name="Consolidated Net Profit before Minority Interest",
                      canonical_name="net_profit_before_minority_interest",
                      periods=[PeriodValue(label=periods[0], evidence=ev(100.0))]),
        LineItemField(field_name="Minority Interest", canonical_name="minority_interest",
                      periods=[PeriodValue(label=periods[0], evidence=ev(5.0))]),
        LineItemField(field_name="Net profit attributable to group",
                      canonical_name="net_profit_attributable_to_group",
                      periods=[PeriodValue(label=periods[0], evidence=ev(95.0))]),
    ]
    extraction = ExtractionResult(document_type="profit_and_loss", statement_line_items=items, periods=periods)
    result = validate_profit_and_loss(extraction)
    assert result.overall_status == "PASS"


# --- Cash flow ----------------------------------------------------------------
def test_cash_flow_reconciles():
    periods = ["Year ended March 31, 2026"]

    def li(canonical, val):
        return LineItemField(field_name=canonical, canonical_name=canonical,
                              periods=[PeriodValue(label=periods[0], evidence=ev(val))])

    items = [
        li("net_cash_from_operating_activities", 100.0),
        li("net_cash_from_investing_activities", -20.0),
        li("net_cash_from_financing_activities", -30.0),
        li("opening_cash_and_equivalents", 200.0),
        li("closing_cash_and_equivalents", 250.0),
    ]
    extraction = ExtractionResult(document_type="cash_flow_statement", statement_line_items=items, periods=periods)
    result = validate_cash_flow(extraction)
    assert result.overall_status == "PASS"


def test_cash_flow_not_applicable_when_missing_components():
    extraction = ExtractionResult(document_type="cash_flow_statement", statement_line_items=[], periods=[])
    result = validate_cash_flow(extraction)
    assert result.overall_status == "NOT_APPLICABLE"
