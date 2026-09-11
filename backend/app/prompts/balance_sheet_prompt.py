"""
prompts/balance_sheet_prompt.py

Document-type-specific extraction prompt for balance sheets (case study
section 33), tuned for the observed dataset: consolidated bank balance
sheets with "Capital and Liabilities" / "Assets" sections, schedule
references, and comparative years, using units that vary from "in '000"
(earlier years) to "in crore" (later years), with fields such as
"Employees stock options" and "Policyholders' funds" appearing only in
some years.
"""
from app.prompts.common import ANTI_HALLUCINATION_RULES

STATEMENT_SCHEMA_HINT = """
Return a JSON object with this shape:

{
  "statement_meta": {
    "statement_title": "string exactly as shown, e.g. 'Consolidated Balance Sheet'",
    "entity_name": "string or null",
    "reporting_period_end": "string exactly as shown, e.g. '31-Mar-2026' or 'As at March 31, 2026'",
    "comparative_period_end": "string or null, e.g. '31-Mar-2025'",
    "currency": "string, e.g. INR",
    "unit_scale": "string exactly as displayed, e.g. 'crore', 'thousand', \"'000\", or null if not shown"
  },
  "line_items": [
    {
      "field_name": "EXACT source label, e.g. 'Deposits'",
      "canonical_name": "well-known equivalent if applicable, e.g. 'total_assets', else null",
      "section": "e.g. 'CAPITAL AND LIABILITIES' or 'ASSETS'",
      "schedule_reference": "string or null",
      "page_number": null,
      "periods": [
        {"label": "reporting period label exactly as shown", "value": null, "raw_text": null, "source_text": null},
        {"label": "comparative period label exactly as shown", "value": null, "raw_text": null, "source_text": null}
      ]
    }
  ],
  "additional_fields": {
    "contingent_liabilities": "...", "bills_for_collection": "...", "notes_reference": "..."
  },
  "periods": ["list of all distinct period labels found"],
  "notes": []
}
"""


def build_balance_sheet_prompt(ocr_text: str, page_count: int) -> str:
    return f"""{ANTI_HALLUCINATION_RULES}

DOCUMENT TYPE: balance_sheet

{STATEMENT_SCHEMA_HINT}

Notes specific to balance sheets:
- Extract EVERY line item under "Capital and Liabilities" and "Assets",
  not just the totals. Include the Total row for each section as its own
  line item with canonical_name "total_capital_and_liabilities" or
  "total_assets" respectively.
- Some years include extra lines not present in other years (e.g.
  "Employees stock options / units outstanding", "Minority interest",
  "Policyholders' funds"). Extract whatever is actually present; do not
  add a line item that is not printed on this specific document.
- Preserve the unit scale exactly (e.g. "(₹ in crore)" vs "₹ in '000").
  Never convert between units yourself.
- Also extract "Contingent liabilities" and "Bills for collection" if
  shown -- they are informational, not part of the Total, but are
  meaningful visible fields.

The document has {page_count} page(s). OCR TEXT FOLLOWS:
---
{ocr_text}
---
Return ONLY the JSON object described above.
"""
