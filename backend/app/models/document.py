from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    """A raw ingested document (plain text or uploaded .txt/.md today;
    PDF/DOCX/OCR/email are scaffolded in app/scaffold/parsers.py per
    FRD section "Multi-Format Document Ingestion").
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(32), default="text")  # text|txt|md
    raw_text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(36))  # users.id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
