from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class ReviewItem(Base):
    """Human-in-the-loop review queue row.

    Created automatically by app/services/rag.py whenever a generated
    answer's confidence score falls below settings.REVIEW_CONFIDENCE_THRESHOLD.
    Reference: FRD section "Human-in-the-Loop Review" / RESPONSIBLE_AI.md.
    """

    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    query_log_id: Mapped[str] = mapped_column(String(36))
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
