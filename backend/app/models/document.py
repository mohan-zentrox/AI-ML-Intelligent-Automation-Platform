from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ClassificationStatus(str, Enum):
    """Provenance of `Document.classification_label` - who stands behind it.

    Kept separate from the label itself so downstream consumers can require
    human-confirmed categories without re-deriving that from confidence
    scores. See FRD section 7 / docs/RESPONSIBLE_AI.md.
    """

    # No classification attempted (CLASSIFICATION_ENABLED=false, or the
    # document had no text).
    UNCLASSIFIED = "unclassified"
    # Model-assigned and confident enough to use without human sign-off.
    AUTO = "auto"
    # Model-assigned but below CLASSIFICATION_REVIEW_THRESHOLD: a ReviewItem
    # exists and the label is provisional until a reviewer rules on it.
    PENDING_REVIEW = "pending_review"
    # A reviewer approved the model's label.
    CONFIRMED = "confirmed"
    # A reviewer replaced the model's label with a different one.
    CORRECTED = "corrected"
    # A reviewer rejected the model's label outright; the label is cleared
    # rather than left in place, so a known-wrong category can never drive
    # downstream routing.
    REJECTED = "rejected"


class Document(Base):
    """A raw ingested document (.txt/.md/.pdf/.docx or pasted text; OCR and
    email remain scaffolded in app/scaffold/parsers.py per FRD section
    "Multi-Format Document Ingestion").

    Classification columns (FRD 7) are populated by
    app/services/ingestion.py via app/services/classification.py at ingest
    time and can be re-run through POST /api/v1/documents/{id}/reclassify.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(32), default="text")  # text|txt|md|pdf|docx
    raw_text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(36))  # users.id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # --- Classification (FRD 7) ---
    # Null while unclassified, and cleared again if a reviewer rejects the
    # proposed label.
    classification_label: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_status: Mapped[str] = mapped_column(
        String(16), default=ClassificationStatus.UNCLASSIFIED.value
    )
    # Stamped from classification.TAXONOMY_VERSION so labels produced under a
    # superseded taxonomy are findable instead of silently stale.
    taxonomy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
