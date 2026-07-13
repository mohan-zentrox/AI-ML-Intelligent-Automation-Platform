from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReviewItemOut(BaseModel):
    id: str
    question: str
    proposed_answer: str
    citations: list[dict]
    confidence: float
    status: str
    final_answer: str | None
    rationale: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewDecisionRequest(BaseModel):
    decision: str  # approved|edited|rejected
    rationale: str
    final_answer: str | None = None
