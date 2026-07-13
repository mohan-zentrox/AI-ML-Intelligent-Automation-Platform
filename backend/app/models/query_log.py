from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class QueryLog(Base):
    """Every RAG Q&A turn, independent of whether it was routed to review."""

    __tablename__ = "query_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON)  # list[{document_id, chunk_id, score}]
    confidence: Mapped[float] = mapped_column(Float)
    refused: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
