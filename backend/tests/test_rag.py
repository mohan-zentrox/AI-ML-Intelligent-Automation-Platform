"""Grounded RAG tests - app/services/rag.py.

Covers: citation correctness, low-confidence routing to the human review
queue, and the insufficient-context refusal path. Confidence/threshold
behaviour is made deterministic by monkeypatching the relevant settings
(pytest's `monkeypatch` fixture auto-restores after each test), rather than
relying on the exact numeric output of the mock hashing embedder.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.models.review_item import ReviewItem, ReviewItemType
from app.models.query_log import QueryLog
from app.services.ingestion import ingest_document
from app.services.rag import INSUFFICIENT_CONTEXT_MESSAGE, answer_question

SAMPLE_DOC_TEXT = (
    "Refunds are processed within thirty days of the original purchase date. "
    "Customers must provide the original receipt to request a refund. "
    "Support tickets for refund requests are handled by the billing team."
)


def _answer_review_count(db_session) -> int:
    return (
        db_session.query(ReviewItem)
        .filter(ReviewItem.item_type == ReviewItemType.ANSWER.value)
        .count()
    )


def _ingest_sample(db_session, mock_provider, in_memory_store, uploaded_by="user-1"):
    return ingest_document(
        db_session,
        title="Refund Policy",
        raw_text=SAMPLE_DOC_TEXT,
        source_type="text",
        uploaded_by=uploaded_by,
        provider=mock_provider,
        vector_store=in_memory_store,
    )


def test_grounded_answer_cites_the_ingested_document(db_session, mock_provider, in_memory_store, monkeypatch):
    settings = get_settings()
    # Force any retrieved chunk to be treated as sufficiently grounded and
    # never routed to review, isolating this test to citation correctness.
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", -1.0)
    monkeypatch.setattr(settings, "REVIEW_CONFIDENCE_THRESHOLD", -1.0)

    document = _ingest_sample(db_session, mock_provider, in_memory_store)

    result = answer_question(
        db_session,
        user_id="user-1",
        question="How many days does a refund take?",
        provider=mock_provider,
        vector_store=in_memory_store,
    )

    assert result.refused is False
    assert result.review_item_id is None
    assert len(result.citations) > 0
    for citation in result.citations:
        assert citation.document_id == document.id
        assert citation.chunk_id  # non-empty

    # The answer text should reference at least one of the numbered markers
    # handed to the mock LLM (it is a template provider that echoes
    # grounded context verbatim, including citation markers).
    assert any(f"[{c.marker}]" in result.answer for c in result.citations)

    # A QueryLog row was written and matches the returned result.
    log = db_session.query(QueryLog).filter_by(id=result.query_log_id).first()
    assert log is not None
    assert log.refused is False
    assert log.answer == result.answer


def test_low_confidence_answer_is_routed_to_review_queue(db_session, mock_provider, in_memory_store, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", -1.0)
    # Impossible to satisfy (max confidence is 1.0) -> every grounded answer
    # must be routed to review.
    monkeypatch.setattr(settings, "REVIEW_CONFIDENCE_THRESHOLD", 1.1)

    _ingest_sample(db_session, mock_provider, in_memory_store)

    result = answer_question(
        db_session,
        user_id="user-1",
        question="How many days does a refund take?",
        provider=mock_provider,
        vector_store=in_memory_store,
    )

    assert result.refused is False
    assert result.review_item_id is not None

    review_item = db_session.query(ReviewItem).filter_by(id=result.review_item_id).first()
    assert review_item is not None
    assert review_item.status == "pending"
    assert review_item.query_log_id == result.query_log_id
    assert review_item.confidence == result.confidence
    assert review_item.proposed_answer == result.answer


def test_high_confidence_answer_is_not_routed_to_review_queue(db_session, mock_provider, in_memory_store, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", -1.0)
    monkeypatch.setattr(settings, "REVIEW_CONFIDENCE_THRESHOLD", -1.0)

    _ingest_sample(db_session, mock_provider, in_memory_store)

    result = answer_question(
        db_session,
        user_id="user-1",
        question="How many days does a refund take?",
        provider=mock_provider,
        vector_store=in_memory_store,
    )

    assert result.review_item_id is None
    # Scoped to answer items: ingesting the sample document may also have
    # queued a classification item (FRD 7), which is unrelated to whether
    # this answer was routed for review.
    assert _answer_review_count(db_session) == 0


def test_insufficient_context_triggers_documented_refusal(db_session, mock_provider, in_memory_store, monkeypatch):
    settings = get_settings()
    # Impossible to satisfy (cosine similarity is bounded by 1.0) -> nothing
    # ever clears the grounding bar, regardless of what's ingested.
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", 2.0)

    _ingest_sample(db_session, mock_provider, in_memory_store)

    result = answer_question(
        db_session,
        user_id="user-1",
        question="How many days does a refund take?",
        provider=mock_provider,
        vector_store=in_memory_store,
    )

    assert result.refused is True
    assert result.answer == INSUFFICIENT_CONTEXT_MESSAGE
    assert result.citations == []
    assert result.confidence == 0.0
    assert result.review_item_id is None

    log = db_session.query(QueryLog).filter_by(id=result.query_log_id).first()
    assert log is not None
    assert log.refused is True

    # Refusals are not routed to the review queue - they are already a safe,
    # documented failure mode (see docs/RESPONSIBLE_AI.md), not a low
    # confidence answer needing a human to adjudicate.
    # Scoped to answer items: ingesting the sample document may also have
    # queued a classification item (FRD 7), which is unrelated to whether
    # this answer was routed for review.
    assert _answer_review_count(db_session) == 0


def test_insufficient_context_with_empty_knowledge_base(db_session, mock_provider, in_memory_store):
    # No documents ingested at all -> vector store is empty -> refusal.
    result = answer_question(
        db_session,
        user_id="user-1",
        question="Anything at all?",
        provider=mock_provider,
        vector_store=in_memory_store,
    )
    assert result.refused is True
    assert result.answer == INSUFFICIENT_CONTEXT_MESSAGE
