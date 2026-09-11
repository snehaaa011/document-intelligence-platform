"""
prompts/common.py

Shared instruction block injected into every document-type-specific prompt
(case study section 8/33). Keeping this in one place means every prompt
enforces the same anti-hallucination and evidence rules.
"""

ANTI_HALLUCINATION_RULES = """
You are extracting information from a source document image/OCR text.
Follow these rules exactly:

1. Only return information that is actually supported by the document text
   or image provided to you. Do not use outside knowledge to fill in
   values that are not visible.
2. Do not infer, estimate, or calculate a missing value and present it as
   if it were extracted. If a field is not visible or not legible, set its
   value to null.
3. Preserve the source's own labels/terminology. Do not rename a field to
   a generic accounting term unless the meaning is unambiguous; when you
   do map to a canonical field, ALSO keep the original label.
4. Preserve negative values. Parentheses or brackets around a number mean
   it is negative, e.g. "(1,234.50)" means -1234.50.
5. Preserve every comparative period separately. Never merge, average, or
   cross-assign a value from one period/column to another.
6. Preserve the currency symbol/code and the displayed unit/scale (e.g.
   "in crore", "in '000", "in thousands") exactly as shown.
7. For every important value, include the literal source text you read it
   from (source_text) and, if you know it, the page number.
8. If OCR text looks corrupted or ambiguous for a specific field, prefer
   returning null over guessing. Do not "correct" an apparently wrong
   number based on what you think it "should" be.
9. Extract ALL meaningful visible fields, not only the minimum required
   ones -- addresses, tax IDs, references, terms, notes, line items, etc.
10. Extract ALL table/line-item rows completely; do not truncate or
    summarize a table.
11. Return ONLY valid JSON matching the requested schema. No prose,
    no markdown code fences, no commentary.
""".strip()
