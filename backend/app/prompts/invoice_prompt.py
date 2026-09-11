"""
prompts/invoice_prompt.py

Document-type-specific extraction prompt for invoices/receipts/tax invoices
(case study section 33). Handles the observed dataset variety: Indian GST
tax invoices, Malaysian GST receipts, Canadian HST invoices, US invoices,
and low-quality photographed invoices.
"""
from app.prompts.common import ANTI_HALLUCINATION_RULES

INVOICE_SCHEMA_HINT = """
Return a JSON object with this shape:

{
  "canonical_fields": {
    "invoice_number": {"value": null, "raw_text": null, "source_text": null, "page_number": null},
    "invoice_date": {...},
    "due_date": {...},
    "vendor_name": "string or null",
    "vendor_address": "string or null",
    "vendor_tax_id": "string or null (GSTIN/VAT/EIN/etc.)",
    "customer_name": "string or null",
    "billing_address": "string or null",
    "shipping_address": "string or null",
    "customer_tax_id": "string or null",
    "purchase_order": "string or null",
    "payment_terms": "string or null",
    "salesperson": "string or null",
    "currency": "ISO-ish code or symbol as shown, e.g. INR/USD/MYR/CAD",
    "subtotal": {value/raw_text/source_text/page_number},
    "discount_amount": {...},
    "tax_amount": {...},
    "shipping_amount": {...},
    "total_amount": {...},
    "amount_paid": {...},
    "amount_due": {...},
    "cash_tendered": {...},
    "change_returned": {...},
    "tax_inclusive": true/false/null
  },
  "line_items": [
    {
      "description": "string",
      "hsn_sac": "string or null",
      "quantity": {value, raw_text, source_text, page_number},
      "unit": "string or null",
      "unit_price": {...},
      "discount_percent": {...},
      "tax_rate": {...},
      "line_total": {...},
      "page_number": null
    }
  ],
  "additional_fields": {
    "any_other_visible_label": "value, e.g. GSTIN summary rows, bank details, delivery note, mode of payment, dispatch doc no, terms of delivery"
  },
  "periods": [],
  "notes": ["any caveats about legibility/OCR quality"]
}
"""


def build_invoice_prompt(ocr_text: str, page_count: int) -> str:
    return f"""{ANTI_HALLUCINATION_RULES}

DOCUMENT TYPE: invoice (this may be a formal tax invoice, a retail
receipt, or a GST/HST/VAT invoice from any country/currency).

{INVOICE_SCHEMA_HINT}

Notes specific to invoices:
- Tax may be shown as CGST/SGST (India), GST (Malaysia/Canada), HST
  (Canada), VAT, or a plain "Tax"/"Sales Tax" line. Sum all tax
  sub-components into tax_amount if a combined total is not shown
  directly, but also keep each named component under additional_fields.
- If line amounts already include tax (common on retail receipts marked
  "Total Includes GST X%"), set tax_inclusive = true.
- Cash/Change fields only apply to cash-register style receipts.
- Watch for handwritten annotations (e.g. round-off, acknowledgement
  scribbles) -- do not treat them as printed field values unless clearly
  legible and clearly a data field (e.g. a handwritten round-off amount
  next to a printed "Round Off" label may be extracted with a note).

The document has {page_count} page(s). OCR TEXT FOLLOWS:
---
{ocr_text}
---
Return ONLY the JSON object described above.
"""
