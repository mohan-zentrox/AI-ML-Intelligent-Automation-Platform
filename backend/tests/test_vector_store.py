"""Retrieval ranking tests - app/services/vector_store.py.

Uses hand-crafted embedding vectors (not the mock hashing embedder) so the
expected cosine-similarity ranking can be verified by hand rather than
depending on hash output.
"""
from __future__ import annotations

from app.services.vector_store import InMemoryVectorStore, VectorRecord


def test_query_ranks_by_cosine_similarity_descending(in_memory_store: InMemoryVectorStore):
    in_memory_store.upsert(
        [
            VectorRecord(chunk_id="a", document_id="doc1", text="chunk a", embedding=[1.0, 0.0, 0.0]),
            VectorRecord(chunk_id="b", document_id="doc1", text="chunk b", embedding=[0.0, 1.0, 0.0]),
            VectorRecord(chunk_id="c", document_id="doc1", text="chunk c", embedding=[0.9, 0.1, 0.0]),
        ]
    )

    results = in_memory_store.query([1.0, 0.0, 0.0], top_k=3)

    assert [r.chunk_id for r in results] == ["a", "c", "b"]
    assert results[0].score == 1.0
    assert results[2].score == 0.0
    assert 0.0 < results[1].score < results[0].score


def test_query_respects_top_k(in_memory_store: InMemoryVectorStore):
    in_memory_store.upsert(
        [
            VectorRecord(chunk_id=f"c{i}", document_id="doc1", text=f"chunk {i}", embedding=[float(i), 1.0, 0.0])
            for i in range(5)
        ]
    )
    results = in_memory_store.query([4.0, 1.0, 0.0], top_k=2)
    assert len(results) == 2


def test_query_on_empty_store_returns_empty_list(in_memory_store: InMemoryVectorStore):
    assert in_memory_store.query([1.0, 0.0, 0.0], top_k=5) == []


def test_upsert_overwrites_existing_chunk_id(in_memory_store: InMemoryVectorStore):
    in_memory_store.upsert(
        [VectorRecord(chunk_id="x", document_id="doc1", text="old", embedding=[1.0, 0.0])]
    )
    in_memory_store.upsert(
        [VectorRecord(chunk_id="x", document_id="doc1", text="new", embedding=[0.0, 1.0])]
    )
    assert in_memory_store.count() == 1
    results = in_memory_store.query([0.0, 1.0], top_k=1)
    assert results[0].text == "new"


def test_delete_by_document_removes_only_that_documents_chunks(in_memory_store: InMemoryVectorStore):
    in_memory_store.upsert(
        [
            VectorRecord(chunk_id="d1c1", document_id="doc1", text="a", embedding=[1.0, 0.0]),
            VectorRecord(chunk_id="d1c2", document_id="doc1", text="b", embedding=[0.0, 1.0]),
            VectorRecord(chunk_id="d2c1", document_id="doc2", text="c", embedding=[1.0, 1.0]),
        ]
    )
    in_memory_store.delete_by_document("doc1")
    assert in_memory_store.count() == 1
    remaining = in_memory_store.query([1.0, 1.0], top_k=5)
    assert [r.chunk_id for r in remaining] == ["d2c1"]
