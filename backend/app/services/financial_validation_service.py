"""
services/financial_validation_service.py

Deterministic financial validation engine (case study sections 14-19, 34,
35). This module NEVER calls an LLM -- validation is pure Python
arithmetic performed against whatever the extraction provider actually
found. If a required input is missing, the relevant check is marked
NOT_APPLICABLE rather than guessed.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.core.config import get_settings
from app.schemas.document import ValidationCheck, ValidationSummary
from app.schemas.extraction import ExtractionResult, LineItemField
from app.utils.number_parser import approximately_equal, effective_tolerance

settings = get_settings()
ABS_TOL = settings.VALIDATION_ABS_TOLERANCE
REL_TOL = settings.VALIDATION_REL_TOLERANCE


def _check(
    name: str,
    formula: str,
    operands: Dict[str, Optional[float]],
    calculated_value: Optional[float],
    reported_value: Optional[float],
    period_label: Optional[str] = None,
    abs_tolerance: float = ABS_TOL,
    rel_tolerance: float = REL_TOL,
) -> ValidationCheck:
    if calculated_value is None or reported_value is None:
        return ValidationCheck(
            name=name,
            formula=formula,
            operands=operands,
            calculated_value=calculated_value,
            reported_value=reported_value,
            variance=None,
            tolerance=None,
            status="NOT_APPLICABLE",
            period_label=period_label,
            message="One or more required inputs were not extracted from the document.",
        )

    ok, variance = approximately_equal(calculated_value, reported_value, abs_tolerance, rel_tolerance)
    tol = effective_tolerance(reported_value, abs_tolerance, rel_tolerance)
    return ValidationCheck(
        name=name,
        formula=formula,
        operands=operands,
        calculated_value=round(calculated_value, 2),
        reported_value=round(reported_value, 2),
        variance=round(variance, 2),
        tolerance=round(tol, 2),
        status="PASS" if ok else "FAIL",
        period_label=period_label,
    )


def _overall_status(checks: List[ValidationCheck]) -> str:
    if any(c.status == "FAIL" for c in checks):
        return "FAIL"
    if all(c.status == "NOT_APPLICABLE" for c in checks):
        return "NOT_APPLICABLE"
    return "PASS"


def _find_line_item(items: List[LineItemField], canonical_name: str) -> Optional[LineItemField]:
    for item in items:
        if item.canonical_name == canonical_name:
            return item
    return None


def _value_for_period(item: Optional[LineItemField], period_label: str) -> Optional[float]:
    if item is None:
        return None
    for p in item.periods:
        if p.label == period_label:
            return p.evidence.value
    return None


# ---------------------------------------------------------------------------
# Invoice validation (section 14)
# ---------------------------------------------------------------------------
def validate_invoice(extraction: ExtractionResult) -> ValidationSummary:
    checks: List[ValidationCheck] = []
    fields = extraction.invoice_fields
    issues: List[str] = []

    if fields is None:
        return ValidationSummary(checks=[], overall_status="NOT_APPLICABLE", issues=["No invoice fields were extracted."])

    # 1. Quantity x Unit Price ~= Line Total (per line item)
    for idx, li in enumerate(extraction.invoice_line_items):
        qty = li.quantity.value if li.quantity else None
        price = li.unit_price.value if li.unit_price else None
        line_total = li.line_total.value if li.line_total else None
        calculated = qty * price if (qty is not None and price is not None) else None
        checks.append(
            _check(
                name=f"line_item_{idx + 1}_quantity_times_price",
                formula="quantity * unit_price ≈ line_total",
                operands={"quantity": qty, "unit_price": price},
                calculated_value=calculated,
                reported_value=line_total,
            )
        )

    # 2. Sum of line totals reconciles with subtotal
    line_totals = [li.line_total.value for li in extraction.invoice_line_items if li.line_total and li.line_total.value is not None]
    subtotal_reported = fields.subtotal.value if fields.subtotal else None
    sum_line_totals = sum(line_totals) if line_totals else None
    checks.append(
        _check(
            name="sum_of_line_totals_vs_subtotal",
            formula="sum(line_total) ≈ subtotal",
            operands={"line_item_count": len(line_totals)},
            calculated_value=sum_line_totals,
            reported_value=subtotal_reported,
        )
    )

    # 3. Taxable Amount + Tax ≈ Total (respecting tax-inclusive flag)
    tax_amount = fields.tax_amount.value if fields.tax_amount else None
    total_amount = fields.total_amount.value if fields.total_amount else None
    discount = fields.discount_amount.value if fields.discount_amount else None
    shipping = fields.shipping_amount.value if fields.shipping_amount else None

    if fields.tax_inclusive:
        checks.append(
            ValidationCheck(
                name="taxable_amount_plus_tax_vs_total",
                formula="total_amount already includes tax (tax_inclusive=true)",
                operands={"tax_amount": tax_amount, "total_amount": total_amount},
                status="NOT_APPLICABLE",
                message="Tax is included in the displayed total; additive check does not apply.",
            )
        )
    else:
        base = subtotal_reported
        components = [v for v in [base, tax_amount] if v is not None]
        calc = None
        if base is not None and tax_amount is not None:
            calc = base + tax_amount
            if discount:
                calc -= abs(discount)
            if shipping:
                calc += shipping
        checks.append(
            _check(
                name="taxable_amount_plus_tax_vs_total",
                formula="subtotal + tax_amount - discount + shipping ≈ total_amount",
                operands={"subtotal": base, "tax_amount": tax_amount, "discount": discount, "shipping": shipping},
                calculated_value=calc,
                reported_value=total_amount,
            )
        )

    # 4. Cash Paid - Total Amount ≈ Change
    cash = fields.cash_tendered.value if fields.cash_tendered else None
    change = fields.change_returned.value if fields.change_returned else None
    calc_change = (cash - total_amount) if (cash is not None and total_amount is not None) else None
    checks.append(
        _check(
            name="cash_minus_total_vs_change",
            formula="cash_tendered - total_amount ≈ change_returned",
            operands={"cash_tendered": cash, "total_amount": total_amount},
            calculated_value=calc_change,
            reported_value=change,
        )
    )

    for c in checks:
        if c.status == "FAIL":
            issues.append(f"{c.name}: calculated {c.calculated_value} vs reported {c.reported_value} (tolerance {c.tolerance})")

    return ValidationSummary(checks=checks, overall_status=_overall_status(checks), issues=issues)


# ---------------------------------------------------------------------------
# Balance sheet validation (section 15)
# ---------------------------------------------------------------------------
def validate_balance_sheet(extraction: ExtractionResult) -> ValidationSummary:
    checks: List[ValidationCheck] = []
    issues: List[str] = []
    items = extraction.statement_line_items
    periods = extraction.periods or _infer_periods(items)

    total_assets_item = _find_line_item(items, "total_assets")
    total_cl_item = _find_line_item(items, "total_capital_and_liabilities")

    asset_items = [i for i in items if i.section == "ASSETS" and i.canonical_name != "total_assets"]
    liability_items = [i for i in items if i.section == "CAPITAL AND LIABILITIES" and i.canonical_name != "total_capital_and_liabilities"]

    for period in periods:
        reported_assets = _value_for_period(total_assets_item, period)
        reported_cl = _value_for_period(total_cl_item, period)

        checks.append(
            _check(
                name="total_capital_liabilities_vs_total_assets",
                formula="Total Capital & Liabilities ≈ Total Assets",
                operands={"total_capital_and_liabilities": reported_cl, "total_assets": reported_assets},
                calculated_value=reported_cl,
                reported_value=reported_assets,
                period_label=period,
            )
        )

        asset_component_values = [_value_for_period(i, period) for i in asset_items]
        asset_component_values = [v for v in asset_component_values if v is not None]
        if len(asset_component_values) >= max(1, len(asset_items) - 0) and asset_component_values:
            sum_assets = sum(asset_component_values)
            checks.append(
                _check(
                    name="sum_of_asset_components_vs_reported_total",
                    formula="sum(asset line items) ≈ reported Total Assets",
                    operands={"component_count": len(asset_component_values)},
                    calculated_value=sum_assets,
                    reported_value=reported_assets,
                    period_label=period,
                )
            )
        else:
            checks.append(
                ValidationCheck(
                    name="sum_of_asset_components_vs_reported_total",
                    formula="sum(asset line items) ≈ reported Total Assets",
                    operands={},
                    status="NOT_APPLICABLE",
                    period_label=period,
                    message="Not all asset components were extracted for this period.",
                )
            )

        liab_component_values = [_value_for_period(i, period) for i in liability_items]
        liab_component_values = [v for v in liab_component_values if v is not None]
        if liab_component_values:
            sum_liab = sum(liab_component_values)
            checks.append(
                _check(
                    name="sum_of_capital_liability_components_vs_reported_total",
                    formula="sum(capital & liability line items) ≈ reported Total Capital & Liabilities",
                    operands={"component_count": len(liab_component_values)},
                    calculated_value=sum_liab,
                    reported_value=reported_cl,
                    period_label=period,
                )
            )
        else:
            checks.append(
                ValidationCheck(
                    name="sum_of_capital_liability_components_vs_reported_total",
                    formula="sum(capital & liability line items) ≈ reported Total Capital & Liabilities",
                    operands={},
                    status="NOT_APPLICABLE",
                    period_label=period,
                    message="Not all capital/liability components were extracted for this period.",
                )
            )

    for c in checks:
        if c.status == "FAIL":
            issues.append(f"{c.name} ({c.period_label}): calculated {c.calculated_value} vs reported {c.reported_value}")

    return ValidationSummary(checks=checks, overall_status=_overall_status(checks), issues=issues)


# ---------------------------------------------------------------------------
# Profit & Loss validation (section 16)
# ---------------------------------------------------------------------------
def validate_profit_and_loss(extraction: ExtractionResult) -> ValidationSummary:
    checks: List[ValidationCheck] = []
    issues: List[str] = []
    items = extraction.statement_line_items
    periods = extraction.periods or _infer_periods(items)

    total_income_item = _find_line_item(items, "total_income")
    total_expenditure_item = _find_line_item(items, "total_expenditure")
    profit_before_mi_item = _find_line_item(items, "net_profit_before_minority_interest")
    minority_interest_item = _find_line_item(items, "minority_interest")
    profit_attributable_item = _find_line_item(items, "net_profit_attributable_to_group")

    for period in periods:
        income = _value_for_period(total_income_item, period)
        expenditure = _value_for_period(total_expenditure_item, period)
        profit_before_mi = _value_for_period(profit_before_mi_item, period)
        minority = _value_for_period(minority_interest_item, period)
        profit_attributable = _value_for_period(profit_attributable_item, period)

        calc_net_profit = (income - expenditure) if (income is not None and expenditure is not None) else None
        checks.append(
            _check(
                name="income_minus_expenditure_vs_net_profit_before_minority_interest",
                formula="Total Income - Total Expenditure ≈ Net Profit before Minority Interest",
                operands={"total_income": income, "total_expenditure": expenditure},
                calculated_value=calc_net_profit,
                reported_value=profit_before_mi,
                period_label=period,
            )
        )

        calc_attributable = (
            (profit_before_mi - minority) if (profit_before_mi is not None and minority is not None) else None
        )
        checks.append(
            _check(
                name="profit_before_minority_minus_minority_vs_attributable",
                formula="Net Profit before Minority Interest - Minority Interest ≈ Net Profit attributable to Group",
                operands={"net_profit_before_minority_interest": profit_before_mi, "minority_interest": minority},
                calculated_value=calc_attributable,
                reported_value=profit_attributable,
                period_label=period,
            )
        )

    for c in checks:
        if c.status == "FAIL":
            issues.append(f"{c.name} ({c.period_label}): calculated {c.calculated_value} vs reported {c.reported_value}")

    return ValidationSummary(checks=checks, overall_status=_overall_status(checks), issues=issues)


# ---------------------------------------------------------------------------
# Cash flow validation (section 17)
# ---------------------------------------------------------------------------
def validate_cash_flow(extraction: ExtractionResult) -> ValidationSummary:
    checks: List[ValidationCheck] = []
    issues: List[str] = []
    items = extraction.statement_line_items
    periods = extraction.periods or _infer_periods(items)

    op_item = _find_line_item(items, "net_cash_from_operating_activities")
    inv_item = _find_line_item(items, "net_cash_from_investing_activities")
    fin_item = _find_line_item(items, "net_cash_from_financing_activities")
    opening_item = _find_line_item(items, "opening_cash_and_equivalents")
    closing_item = _find_line_item(items, "closing_cash_and_equivalents")

    for period in periods:
        op = _value_for_period(op_item, period)
        inv = _value_for_period(inv_item, period)
        fin = _value_for_period(fin_item, period)
        opening = _value_for_period(opening_item, period)
        closing = _value_for_period(closing_item, period)

        components = [v for v in [op, inv, fin] if v is not None]
        calc_net_increase = sum(components) if len(components) == 3 else None
        checks.append(
            _check(
                name="operating_plus_investing_plus_financing_vs_net_increase",
                formula="Operating CF + Investing CF + Financing CF ≈ Net Increase in Cash",
                operands={"operating": op, "investing": inv, "financing": fin},
                calculated_value=calc_net_increase,
                reported_value=(opening is not None and closing is not None and (closing - opening)) or None,
                period_label=period,
            )
        )

        calc_closing = (opening + calc_net_increase) if (opening is not None and calc_net_increase is not None) else None
        checks.append(
            _check(
                name="opening_plus_net_increase_vs_closing",
                formula="Opening Cash + Net Increase in Cash ≈ Closing Cash",
                operands={"opening_cash": opening, "net_increase": calc_net_increase},
                calculated_value=calc_closing,
                reported_value=closing,
                period_label=period,
            )
        )

    for c in checks:
        if c.status == "FAIL":
            issues.append(f"{c.name} ({c.period_label}): calculated {c.calculated_value} vs reported {c.reported_value}")

    return ValidationSummary(checks=checks, overall_status=_overall_status(checks), issues=issues)


def _infer_periods(items: List[LineItemField]) -> List[str]:
    seen = []
    for item in items:
        for p in item.periods:
            if p.label not in seen:
                seen.append(p.label)
    return seen


VALIDATORS = {
    "invoice": validate_invoice,
    "balance_sheet": validate_balance_sheet,
    "profit_and_loss": validate_profit_and_loss,
    "cash_flow_statement": validate_cash_flow,
}


def run_validation(document_type: str, extraction: ExtractionResult) -> ValidationSummary:
    validator = VALIDATORS.get(document_type)
    if validator is None:
        return ValidationSummary(checks=[], overall_status="NOT_APPLICABLE", issues=[f"No validator for {document_type}"])
    return validator(extraction)
