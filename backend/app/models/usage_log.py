from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UsageLog(Base):
    """One row per LLM/embedding provider call - tokens, cost, latency.

    Populated from app/services/llm_provider.py's LLMResponse/EmbeddingResponse
    metadata so cost tracking works identically for the mock and litellm
    providers (mock always reports cost_usd=0.0).
    """

    __tablename__ = "usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(32))  # "embedding" | "completion"
    provider: Mapped[str] = mapped_column(String(32))  # "mock" | "litellm"
    model: Mapped[str] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
