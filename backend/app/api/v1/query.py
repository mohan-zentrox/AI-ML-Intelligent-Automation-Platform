"""
Grounded RAG query endpoint.

Reference: FRD section "Retrieval-Augmented Generation".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import Principal, require_role
from app.core.security import Role
from app.db.session import get_db
from app.schemas.query import CitationOut, QueryRequest, QueryResponse
from app.services.rag import answer_question

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
def query(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*Role)),
) -> QueryResponse:
    result = answer_question(db, user_id=principal.user_id, question=payload.question)
    return QueryResponse(
        answer=result.answer,
        citations=[CitationOut(**vars(c)) for c in result.citations],
        confidence=result.confidence,
        refused=result.refused,
        query_log_id=result.query_log_id,
        routed_to_review=result.review_item_id is not None,
    )
