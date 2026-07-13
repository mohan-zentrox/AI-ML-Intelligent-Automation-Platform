"""
Human-in-the-loop review queue endpoints.

Reference: FRD section "Human-in-the-Loop Review" / docs/RESPONSIBLE_AI.md.
Every reviewer decision is captured to the `feedback` table for future
eval-dataset construction (promptfoo regression fixtures).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import Principal, require_role
from app.core.security import Role
from app.db.session import get_db
from app.models.feedback import Feedback
from app.models.review_item import ReviewItem, ReviewStatus
from app.schemas.review import ReviewDecisionRequest, ReviewItemOut

router = APIRouter(prefix="/review", tags=["review"])

_REVIEW_ROLES = (Role.ADMIN, Role.REVIEWER)

_VALID_DECISIONS = {"approved", "edited", "rejected"}


@router.get("/queue", response_model=list[ReviewItemOut])
def list_review_queue(
    status: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*_REVIEW_ROLES)),
) -> list[ReviewItemOut]:
    q = db.query(ReviewItem)
    if status:
        q = q.filter(ReviewItem.status == status)
    items = q.order_by(ReviewItem.created_at.asc()).all()
    return [ReviewItemOut.model_validate(i) for i in items]


@router.post("/queue/{review_item_id}/decision", response_model=ReviewItemOut)
def record_decision(
    review_item_id: str,
    payload: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*_REVIEW_ROLES)),
) -> ReviewItemOut:
    if payload.decision not in _VALID_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"decision must be one of {sorted(_VALID_DECISIONS)}",
        )
    item = db.query(ReviewItem).filter_by(id=review_item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    if item.status != ReviewStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"Review item already resolved as '{item.status}'")

    item.status = payload.decision
    item.reviewer_id = principal.user_id
    item.rationale = payload.rationale
    item.final_answer = payload.final_answer if payload.decision == "edited" else (
        item.proposed_answer if payload.decision == "approved" else None
    )
    item.resolved_at = datetime.utcnow()
    db.add(item)

    db.add(
        Feedback(
            review_item_id=item.id,
            reviewer_id=principal.user_id,
            decision=payload.decision,
            rationale=payload.rationale,
        )
    )
    db.commit()
    db.refresh(item)
    return ReviewItemOut.model_validate(item)
