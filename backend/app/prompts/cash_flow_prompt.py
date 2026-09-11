"""
prompts/cash_flow_prompt.py

Document-type-specific extraction prompt for cash flow statements (case
study section 33), tuned for the observed dataset: consolidated cash flow
statements with Operating/Investing/Financing sections spanning 1-2 pages,
heavy use of bracketed negative values.
"""
from app.prompts.common import ANTI_HALLUCINATION_RULES
from app.prompts.balance_sheet_prompt import STATEMENT_SCHEMA_HINT


def build_cash_flow_prompt(ocr_text: str, page_count: int) -> str:
    return f"""{ANTI_HALLUCINATION_RULES}

DOCUMENT TYPE: cash_flow_statement

{STATEMENT_SCHEMA_HINT}

Notes specific to cash flow statements:
- This statement commonly spans multiple pages; preserve page_number per
  line item so evidence remains traceable.
- Sections typically include "Cash flows from operating activities",
  "Cash flows from investing activities", "Cash flows from financing
  activities", and a reconciliation of opening/closing cash. Extract every
  line item under each section, not just subtotals.
- Map clear totals to canonical names where applicable:
    "Net cash flow(s) from operating activities" -> "net_cash_from_operating_activities"
    "Net cash flow from / (used in) investing activities" -> "net_cash_from_investing_activities"
    "Net cash flow from / (used in) financing activities" -> "net_cash_from_financing_activities"
    "Cash and cash equivalents at the beginning of the year" -> "opening_cash_and_equivalents"
    "Cash and cash equivalents at the end of the year" -> "closing_cash_and_equivalents"
- Numbers in parentheses are cash OUTFLOWS (negative). Preserve the sign.
- If an adjustment line (e.g. FX translation, cash acquired on
  acquisition) is not printed on this specific document, do not invent it.

The document has {page_count} page(s). OCR TEXT FOLLOWS:
---
{ocr_text}
---
Return ONLY the JSON object described above.
"""
