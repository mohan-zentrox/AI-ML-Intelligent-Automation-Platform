"""
Document ingestion pipeline: store raw doc -> classify -> chunk -> embed -> index.

Reference: FRD section "Document Ingestion Pipeline". Format-specific
parsing happens upstream in app/services/parsers.py (.txt/.md/.pdf/.docx);
this module only ever sees plain text, so new formats plug in without
touching classification, chunking, embedding, or vector storage. OCR of
scanned PDFs and email parsing remain scaffolded in app/scaffold/parsers.py.

Classification (FRD 7) runs once per document, before chunking, and is
advisory: a failed or low-confidence classification never blocks ingestion,
it just leaves the document provisionally labelled and queued for a human
(see `classify_and_route`).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.chunk import Chunk
from app.models.document import ClassificationStatus, Document
from app.models.review_item import ReviewItem, ReviewItemType, ReviewStatus
from app.models.usage_log import UsageLog
from app.services.chunking import chunk_text
from app.services.classification import UNKNOWN_LABEL, ClassificationResult, classify_document
from app.services.llm_provider import LLMProvider, get_llm_provider
from app.services.vector_store import VectorRecord, VectorStoreRepository, get_vector_store

settings = get_settings()


def ingest_document(
    db: Session,
    *,
    title: str,
    raw_text: str,
    source_type: str,
    uploaded_by: str,
    provider: LLMProvider | None = None,
    vector_store: VectorStoreRepository | None = None,
) -> Document:
    provider = provider or get_llm_provider()
    vector_store = vector_store or get_vector_store()

    document = Document(
        title=title,
        source_type=source_type,
        raw_text=raw_text,
        char_count=len(raw_text),
        uploaded_by=uploaded_by,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    if settings.CLASSIFICATION_ENABLED:
        classify_and_route(db, document, actor_id=uploaded_by, provider=provider)

    chunks = chunk_text(
        raw_text,
        chunk_size_tokens=settings.CHUNK_SIZE_TOKENS,
        overlap_tokens=settings.CHUNK_OVERLAP_TOKENS,
    )
    if not chunks:
        return document

    embed_result = provider.embed([c.text for c in chunks])

    chunk_rows: list[Chunk] = []
    vector_records: list[VectorRecord] = []
    for chunk, vector in zip(chunks, embed_result.vectors):
        chunk_row = Chunk(
            document_id=document.id,
            chunk_index=chunk.index,
            text=chunk.text,
            token_count=chunk.token_count,
            embedding=vector,
            embedding_model=embed_result.model,
        )
        chunk_rows.append(chunk_row)

    db.add_all(chunk_rows)
    db.commit()
    for row in chunk_rows:
        db.refresh(row)

    for chunk_row, vector in zip(chunk_rows, embed_result.vectors):
        vector_records.append(
            VectorRecord(
                chunk_id=chunk_row.id,
                document_id=document.id,
                text=chunk_row.text,
                embedding=vector,
                metadata={"chunk_index": chunk_row.chunk_index, "title": title},
            )
        )
    vector_store.upsert(vector_records)

    return document


def classify_and_route(
    db: Session,
    document: Document,
    *,
    actor_id: str,
    provider: LLMProvider | None = None,
) -> ClassificationResult:
    """Classify `document`, persist the outcome, and queue it for a human if
    the label cannot be trusted on its own.

    Shared by ingestion and POST /api/v1/documents/{id}/reclassify, so both
    paths produce identical state (label, status, usage ledger entry, review
    item) rather than drifting apart.
    """
    result = classify_document(document.raw_text, provider=provider)

    if result.usage is not None:
        db.add(
            UsageLog(
                user_id=actor_id,
                operation="classification",
                provider=result.usage.provider,
                model=result.usage.model,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                total_tokens=result.usage.total_tokens,
                cost_usd=result.usage.cost_usd,
                latency_ms=result.usage.latency_ms,
            )
        )

    document.classification_confidence = result.confidence
    document.taxonomy_version = result.taxonomy_version
    document.classified_at = datetime.utcnow()

    if result.needs_review:
        # An unusable label is stored as NULL, not as the literal "unknown":
        # downstream routing checks for "is this document classified?", and a
        # sentinel string would answer yes.
        document.classification_label = None if result.label == UNKNOWN_LABEL else result.label
        document.classification_status = ClassificationStatus.PENDING_REVIEW.value
    else:
        document.classification_label = result.label
        document.classification_status = ClassificationStatus.AUTO.value

    db.add(document)
    db.commit()
    db.refresh(document)

    if result.needs_review:
        _queue_classification_review(db, document, result)

    return result


def _queue_classification_review(
    db: Session, document: Document, result: ClassificationResult
) -> ReviewItem:
    """Open a pending classification review for `document`.

    Any earlier pending classification review for the same document is
    withdrawn first, so re-running the classifier cannot leave two competing
    proposals in the queue for one document.
    """
    superseded = (
        db.query(ReviewItem)
        .filter(
            ReviewItem.document_id == document.id,
            ReviewItem.item_type == ReviewItemType.CLASSIFICATION.value,
            ReviewItem.status == ReviewStatus.PENDING.value,
        )
        .all()
    )
    for stale in superseded:
        stale.status = ReviewStatus.REJECTED.value
        stale.rationale = "Superseded by a newer classification run."
        stale.resolved_at = datetime.utcnow()
        db.add(stale)

    review_item = ReviewItem(
        item_type=ReviewItemType.CLASSIFICATION.value,
        document_id=document.id,
        question=f"Classify document: {document.title}",
        proposed_answer=result.label,
        citations=[
            {
                "marker": 1,
                "document_id": document.id,
                "chunk_id": "",
                "score": result.confidence,
                "snippet": document.raw_text[:240],
            }
        ],
        confidence=result.confidence,
        status=ReviewStatus.PENDING.value,
    )
    db.add(review_item)
    db.commit()
    db.refresh(review_item)
    return review_item
