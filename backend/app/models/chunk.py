from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Chunk(Base):
    """A chunk of a Document plus a copy of its embedding.

    The embedding is persisted here (as JSON) *and* in the pluggable vector
    store (app/services/vector_store.py). Keeping a relational copy makes it
    trivial to rebuild the vector index from Postgres if the vector store is
    ever swapped or wiped, and keeps citation lookups (chunk -> doc) simple
    SQL joins instead of round-tripping through Chroma metadata.
    """

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list] = mapped_column(JSON)  # list[float]
    embedding_model: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
