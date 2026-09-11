"""
prompts/profit_and_loss_prompt.py

Document-type-specific extraction prompt for profit & loss / income
statements (case study section 33), tuned for the observed dataset:
consolidated bank P&L accounts with Income/Expenditure/Profit/
Appropriations/EPS sections.
"""
from app.prompts.common import ANTI_HALLUCINATION_RULES
from app.prompts.balance_sheet_prompt import STATEMENT_SCHEMA_HINT


def build_profit_and_loss_prompt(ocr_text: str, page_count: int) -> str:
    return f"""{ANTI_HALLUCINATION_RULES}

DOCUMENT TYPE: profit_and_loss

{STATEMENT_SCHEMA_HINT}

Notes specific to profit & loss statements:
- Use the ACTUAL section headings and line labels present (e.g. "I
  INCOME", "II EXPENDITURE", "III PROFIT", "IV APPROPRIATIONS", "V
  EARNINGS PER EQUITY SHARE"). Do NOT force generic terms like
  "revenue" or "COGS" onto a banking P&L if those terms are not printed.
- Map obviously equivalent totals to canonical_name where clear:
    "Total" under INCOME -> "total_income"
    "Total" under EXPENDITURE -> "total_expenditure"
    "Consolidated Net Profit for the year before Minority Interest" ->
        "net_profit_before_minority_interest"
    "Minority Interest" (in the PROFIT section) -> "minority_interest"
    "Consolidated Net Profit for the year attributable to the group" ->
        "net_profit_attributable_to_group"
    "Basic" EPS -> "earnings_per_share_basic"
    "Diluted" EPS -> "earnings_per_share_diluted"
  Still keep the original field_name for every line item.
- Extract every appropriation line (transfers to reserves, dividends,
  brought-forward/carried-over profit) individually; do not summarize.
- Extract EPS figures even though they are per-share, not aggregate
  amounts -- store them as their own line items with the correct unit
  (per-share, not crore/thousand).

The document has {page_count} page(s). OCR TEXT FOLLOWS:
---
{ocr_text}
---
Return ONLY the JSON object described above.
"""
