"""
Human-in-the-loop review queue endpoints.

Reference: FRD section "Human-in-the-Loop Review" / docs/RESPONSIBLE_AI.md.
One queue carries both low-confidence RAG answers and low-confidence
document classifications (FRD 7) - see app/models/review_item.py for how the
two share a row shape. Every reviewer decision is captured to the `feedback`
table for future eval-dataset construction (promptfoo regression fixtures).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import Principal, require_role
from app.core.security import Role
from app.db.session import get_db
from app.models.document import ClassificationStatus, Document
from app.models.feedback import Feedback
from app.models.review_item import ReviewItem, ReviewItemType, ReviewStatus
from app.schemas.review import ReviewDecisionRequest, ReviewItemOut
from app.services.classification import TAXONOMY

router = APIRouter(prefix="/review", tags=["review"])

_REVIEW_ROLES = (Role.ADMIN, Role.REVIEWER)

_VALID_DECISIONS = {"approved", "edited", "rejected"}


@router.get("/queue", response_model=list[ReviewItemOut])
def list_review_queue(
    status: str | None = None,
    item_type: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*_REVIEW_ROLES)),
) -> list[ReviewItemOut]:
    q = db.query(ReviewItem)
    if status:
        q = q.filter(ReviewItem.status == status)
    if item_type:
        valid_types = {t.value for t in ReviewItemType}
        if item_type not in valid_types:
            raise HTTPException(
                status_code=400, detail=f"item_type must be one of {sorted(valid_types)}"
            )
        q = q.filter(ReviewItem.item_type == item_type)
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

    is_classification = item.item_type == ReviewItemType.CLASSIFICATION.value
    if is_classification:
        if payload.decision == "edited" and payload.final_answer not in TAXONOMY:
            # A free-text "corrected label" would silently break routing, so
            # an edit here must name a real taxonomy category.
            raise HTTPException(
                status_code=400,
                detail=(
                    "For a classification item, `final_answer` must be a taxonomy "
                    f"label. Known labels: {sorted(TAXONOMY)}"
                ),
            )
        if payload.decision == "approved" and item.proposed_answer not in TAXONOMY:
            # The classifier produced no usable label (UNKNOWN_LABEL), so
            # there is nothing to approve - the reviewer has to supply one.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The classifier proposed '{item.proposed_answer}', which is not a "
                    "taxonomy label. Submit an 'edited' decision with the correct "
                    "label, or 'rejected' to leave the document unclassified."
                ),
            )

    item.status = payload.decision
    item.reviewer_id = principal.user_id
    item.rationale = payload.rationale
    item.final_answer = payload.final_answer if payload.decision == "edited" else (
        item.proposed_answer if payload.decision == "approved" else None
    )
    item.resolved_at = datetime.utcnow()
    db.add(item)

    if is_classification:
        _apply_classification_decision(db, item, payload.decision)

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


def _apply_classification_decision(db: Session, item: ReviewItem, decision: str) -> None:
    """Write a resolved classification review back onto its document.

    Without this the queue would be decorative: the point of confirming a
    label is that the confirmed label - and the fact a human stands behind
    it - is what downstream routing then reads off the Document row.

    A rejection clears the label rather than leaving it in place, so a
    category a human has explicitly called wrong can never drive routing.
    Re-labelling a rejected document means re-running
    POST /documents/{id}/reclassify or editing the item to a correct label.
    """
    if not item.document_id:
        return
    document = db.query(Document).filter_by(id=item.document_id).first()
    if not document:
        return

    if decision == "approved":
        document.classification_label = item.proposed_answer
        document.classification_status = ClassificationStatus.CONFIRMED.value
    elif decision == "edited":
        document.classification_label = item.final_answer
        document.classification_status = ClassificationStatus.CORRECTED.value
        # The label is now a human's, not the model's - a stale model
        # confidence next to it would be misleading.
        document.classification_confidence = None
    else:  # rejected
        document.classification_label = None
        document.classification_status = ClassificationStatus.REJECTED.value
    db.add(document)
