"""Document ingestion pipeline tests - app/services/ingestion.py.

Covers: raw document persisted, chunking + embedding wired end to end, and
chunk rows kept in sync with the vector store (both backed by the same
`chunk_id`s so citations in rag.py can resolve back to source chunks).
"""
from __future__ import annotations

from app.models.chunk import Chunk
from app.models.document import Document
from app.services.ingestion import ingest_document


def test_ingest_document_persists_raw_document(db_session, mock_provider, in_memory_store):
    text = "Alpha bravo charlie delta echo foxtrot golf hotel."
    document = ingest_document(
        db_session,
        title="Phonetic Alphabet",
        raw_text=text,
        source_type="text",
        uploaded_by="user-1",
        provider=mock_provider,
        vector_store=in_memory_store,
    )

    stored = db_session.query(Document).filter_by(id=document.id).first()
    assert stored is not None
    assert stored.raw_text == text
    assert stored.char_count == len(text)
    assert stored.title == "Phonetic Alphabet"


def test_ingest_document_creates_chunks_and_vector_records(db_session, mock_provider, in_memory_store):
    text = " ".join(f"word{i}" for i in range(500))  # long enough for multiple chunks
    document = ingest_document(
        db_session,
        title="Long Doc",
        raw_text=text,
        source_type="text",
        uploaded_by="user-1",
        provider=mock_provider,
        vector_store=in_memory_store,
    )

    chunk_rows = db_session.query(Chunk).filter_by(document_id=document.id).all()
    assert len(chunk_rows) > 1  # default chunk size (200) forces multiple chunks for 500 words

    # Every relational chunk row has a matching vector-store record with the
    # same id and a non-empty embedding, and the store's count matches.
    assert in_memory_store.count() == len(chunk_rows)
    for row in chunk_rows:
        assert len(row.embedding) > 0
        results = in_memory_store.query(row.embedding, top_k=1)
        assert results[0].chunk_id == row.id
        assert results[0].document_id == document.id


def test_ingest_document_empty_text_creates_document_with_no_chunks(db_session, mock_provider, in_memory_store):
    # chunk_text() returns [] for whitespace-only content; ingestion should
    # not error, just produce a document with zero chunks.
    document = ingest_document(
        db_session,
        title="Empty",
        raw_text="   ",
        source_type="text",
        uploaded_by="user-1",
        provider=mock_provider,
        vector_store=in_memory_store,
    )
    chunk_rows = db_session.query(Chunk).filter_by(document_id=document.id).all()
    assert chunk_rows == []
    assert in_memory_store.count() == 0
