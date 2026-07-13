"""
SCAFFOLD ONLY - Structured field extraction.

Reference: FRD section 8 "Structured Field Extraction". Intended to pull a
schema-defined set of fields (e.g. invoice_number, total_amount, due_date)
out of a classified document (see classification.py) and return them as
validated, typed data rather than free text.

Not wired into the API yet.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ExtractionSchema(BaseModel):
    """TODO(FRD 8.1): user/admin-defined field schema for a document
    category, e.g. {"invoice_number": "string", "total_amount": "number"}.
    Would be persisted per-classification-label and versioned.
    """

    name: str
    fields: dict[str, str]  # field_name -> type hint ("string"|"number"|"date"|...)


def extract_fields(document_text: str, schema: ExtractionSchema) -> dict[str, Any]:
    """TODO(FRD 8.2): extract `schema.fields` from `document_text`.

    Suggested approach: an LLMProvider.complete() call constrained to return
    JSON matching `schema.fields` (function-calling / structured-output mode
    where the active provider supports it), validated against a
    pydantic model built dynamically from the schema. Extractions below a
    confidence threshold should route to the same human review queue used
    by RAG answers (app/models/review_item.py) for consistency, rather than
    introducing a second review mechanism.
    """
    raise NotImplementedError("Structured field extraction is scaffolded - see FRD 8.2")
