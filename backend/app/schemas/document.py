from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DocumentCreateText(BaseModel):
    title: str
    text: str = Field(min_length=1)


class DocumentOut(BaseModel):
    id: str
    title: str
    source_type: str
    char_count: int
    chunk_count: int
    created_at: datetime

    # --- Classification (FRD 7) ---
    # `classification_label` is null when classification is disabled, the
    # classifier could not produce a usable label, or a reviewer rejected the
    # proposed one - `classification_status` says which.
    classification_label: str | None = None
    classification_confidence: float | None = None
    classification_status: str = "unclassified"
    taxonomy_version: str | None = None
    classified_at: datetime | None = None

    model_config = {"from_attributes": True}


class CategoryOut(BaseModel):
    """One taxonomy entry, as served by GET /documents/taxonomy so clients
    can render label pickers without hardcoding the label set."""

    label: str
    description: str


class TaxonomyOut(BaseModel):
    version: str
    categories: list[CategoryOut]
