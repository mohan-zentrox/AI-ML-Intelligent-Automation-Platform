"""
Grounded RAG orchestration.

Reference: FRD sections "Retrieval-Augmented Generation" and
"Responsible AI - Grounding & Refusal" (see docs/RESPONSIBLE_AI.md).

Pipeline for POST /api/v1/query:
  1. Embed the question via the active LLMProvider.
  2. Retrieve top-k chunks from the active VectorStoreRepository (cosine
     similarity).
  3. If no chunk clears `settings.SIMILARITY_THRESHOLD`, refuse rather than
     let the LLM hallucinate an ungrounded answer.
  4. Otherwise build a grounded prompt with numbered citation markers and
     call the LLM provider for a completion.
  5. Compute an answer confidence score from retrieval strength; log the
     usage/cost and, if confidence is below
     `settings.REVIEW_CONFIDENCE_THRESHOLD`, write a ReviewItem for human
     triage.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.query_log import QueryLog
from app.models.review_item import ReviewItem, ReviewItemType
from app.models.usage_log import UsageLog
from app.services.llm_provider import LLMProvider, get_llm_provider
from app.services.vector_store import ScoredChunk, VectorStoreRepository, get_vector_store

settings = get_settings()

INSUFFICIENT_CONTEXT_MESSAGE = (
    "I don't have enough grounded context in the knowledge base to answer "
    "this question confidently. Please ingest a relevant document or "
    "rephrase your question. (Refusal reason: no retrieved chunk cleared "
    "the similarity threshold.)"
)


@dataclass
class Citation:
    marker: int
    document_id: str
    chunk_id: str
    score: float
    snippet: str


@dataclass
class RagResult:
    answer: str
    citations: list[Citation]
    confidence: float
    refused: bool
    query_log_id: str
    review_item_id: str | None = None


def _build_grounded_prompt(question: str, scored_chunks: list[ScoredChunk]) -> tuple[str, list[Citation]]:
    citations: list[Citation] = []
    context_lines = []
    for i, sc in enumerate(scored_chunks, start=1):
        context_lines.append(f"[{i}] {sc.text}")
        citations.append(
            Citation(
                marker=i,
                document_id=sc.document_id,
                chunk_id=sc.chunk_id,
                score=sc.score,
                snippet=sc.text[:240],
            )
        )
    context_block = "\n".join(context_lines)
    prompt = (
        "You are Project Synapse, a grounded document-QA assistant.\n"
        "Answer the QUESTION using ONLY the numbered CONTEXT below. Cite the "
        "source of every claim using its [n] marker. If the context does not "
        "contain the answer, say so explicitly instead of guessing.\n\n"
        f"CONTEXT:\n{context_block}\n"
        f"QUESTION:\n{question}\n"
        "INSTRUCTIONS:\nAnswer concisely and include [n] citation markers."
    )
    return prompt, citations


def _compute_confidence(scored_chunks: list[ScoredChunk]) -> float:
    """Confidence heuristic: driven by top retrieval score and agreement
    (score spread) across the retrieved set. Bounded to [0, 1].

    This is intentionally simple/transparent (not a black box) so reviewers
    can reason about why an answer was or wasn't routed to human review -
    see docs/RESPONSIBLE_AI.md.
    """
    if not scored_chunks:
        return 0.0
    top_score = max(0.0, min(1.0, scored_chunks[0].score))
    if len(scored_chunks) > 1:
        second = max(0.0, min(1.0, scored_chunks[1].score))
        agreement_bonus = min(0.1, second * 0.1)
    else:
        agreement_bonus = 0.0
    confidence = min(1.0, top_score * 0.9 + agreement_bonus)
    return round(confidence, 4)


def answer_question(
    db: Session,
    *,
    user_id: str,
    question: str,
    provider: LLMProvider | None = None,
    vector_store: VectorStoreRepository | None = None,
    top_k: int | None = None,
) -> RagResult:
    provider = provider or get_llm_provider()
    vector_store = vector_store or get_vector_store()
    top_k = top_k or settings.RETRIEVAL_TOP_K

    embed_result = provider.embed([question])
    question_embedding = embed_result.vectors[0]

    _log_usage(
        db,
        user_id=user_id,
        operation="embedding",
        provider=provider.name,
        model=embed_result.model,
        prompt_tokens=embed_result.prompt_tokens,
        completion_tokens=0,
        cost_usd=embed_result.cost_usd,
        latency_ms=embed_result.latency_ms,
    )

    all_candidates = vector_store.query(question_embedding, top_k=top_k)
    grounded_chunks = [c for c in all_candidates if c.score >= settings.SIMILARITY_THRESHOLD]

    if not grounded_chunks:
        query_log = QueryLog(
            user_id=user_id,
            question=question,
            answer=INSUFFICIENT_CONTEXT_MESSAGE,
            citations=[],
            confidence=0.0,
            refused=True,
        )
        db.add(query_log)
        db.commit()
        db.refresh(query_log)
        return RagResult(
            answer=INSUFFICIENT_CONTEXT_MESSAGE,
            citations=[],
            confidence=0.0,
            refused=True,
            query_log_id=query_log.id,
        )

    prompt, citations = _build_grounded_prompt(question, grounded_chunks)
    completion = provider.complete(prompt)

    _log_usage(
        db,
        user_id=user_id,
        operation="completion",
        provider=provider.name,
        model=completion.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        cost_usd=completion.cost_usd,
        latency_ms=completion.latency_ms,
    )

    confidence = _compute_confidence(grounded_chunks)

    citations_payload = [
        {
            "marker": c.marker,
            "document_id": c.document_id,
            "chunk_id": c.chunk_id,
            "score": c.score,
            "snippet": c.snippet,
        }
        for c in citations
    ]

    query_log = QueryLog(
        user_id=user_id,
        question=question,
        answer=completion.text,
        citations=citations_payload,
        confidence=confidence,
        refused=False,
    )
    db.add(query_log)
    db.commit()
    db.refresh(query_log)

    review_item_id = None
    if confidence < settings.REVIEW_CONFIDENCE_THRESHOLD:
        review_item = ReviewItem(
            item_type=ReviewItemType.ANSWER.value,
            query_log_id=query_log.id,
            question=question,
            proposed_answer=completion.text,
            citations=citations_payload,
            confidence=confidence,
            status="pending",
        )
        db.add(review_item)
        db.commit()
        db.refresh(review_item)
        review_item_id = review_item.id

    return RagResult(
        answer=completion.text,
        citations=citations,
        confidence=confidence,
        refused=False,
        query_log_id=query_log.id,
        review_item_id=review_item_id,
    )


def _log_usage(
    db: Session,
    *,
    user_id: str,
    operation: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: float,
) -> None:
    db.add(
        UsageLog(
            user_id=user_id,
            operation=operation,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
    )
    db.commit()
