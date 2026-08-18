"""
Document ingestion pipeline: store raw doc -> chunk -> embed -> index.

Reference: FRD section "Document Ingestion Pipeline". Format-specific
parsing happens upstream in app/services/parsers.py (.txt/.md/.pdf/.docx);
this module only ever sees plain text, so new formats plug in without
touching chunking, embedding, or vector storage. OCR of scanned PDFs and
email parsing remain scaffolded in app/scaffold/parsers.py.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.services.chunking import chunk_text
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
