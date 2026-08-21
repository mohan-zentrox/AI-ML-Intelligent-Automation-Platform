from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReviewItemOut(BaseModel):
    id: str
    # "answer" (low-confidence RAG answer) or "classification" (low-confidence
    # document label). Drives how a client renders the item and what a valid
    # `final_answer` looks like - see app/models/review_item.py.
    item_type: str
    document_id: str | None
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
    # For "edited" items: the corrected answer text, or - on a classification
    # item - the corrected taxonomy label.
    final_answer: str | None = None
