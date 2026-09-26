from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class ReviewItemType(str, Enum):
    """What kind of model output is awaiting a human.

    Both kinds share one queue deliberately: reviewers get a single place to
    work, and every decision lands in the same `feedback` table regardless of
    which subsystem produced it. See FRD section 7.1 / docs/RESPONSIBLE_AI.md.
    """

    # Low-confidence grounded RAG answer (app/services/rag.py).
    ANSWER = "answer"
    # Low-confidence document classification (app/services/classification.py).
    CLASSIFICATION = "classification"


class ReviewItem(Base):
    """Human-in-the-loop review queue row.

    Created automatically whenever a model output falls below its confidence
    threshold: RAG answers below settings.REVIEW_CONFIDENCE_THRESHOLD
    (app/services/rag.py) and document classifications below
    settings.CLASSIFICATION_REVIEW_THRESHOLD (app/services/ingestion.py).
    Reference: FRD section "Human-in-the-Loop Review" / RESPONSIBLE_AI.md.

    Two generic columns carry both item types:

      * `question`        - what the model was asked. A user question for
                            ANSWER items; "Classify document: <title>" for
                            CLASSIFICATION items.
      * `proposed_answer` - what the model produced. The generated answer for
                            ANSWER items; the proposed taxonomy label for
                            CLASSIFICATION items.

    `query_log_id` and `document_id` are the type-specific back-references and
    are each populated only for their own item type.
    """

    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_type: Mapped[str] = mapped_column(
        String(16), default=ReviewItemType.ANSWER.value, index=True
    )
    # Set for ANSWER items only (query_logs.id).
    query_log_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Set for CLASSIFICATION items only (documents.id).
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    proposed_answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default=ReviewStatus.PENDING.value)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
