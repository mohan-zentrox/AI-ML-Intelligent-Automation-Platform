"""Tests for `PgVectorStore` against a real PostgreSQL + pgvector server.

Skipped unless `TEST_DATABASE_URL` points at one, because there is no way to
fake this usefully: the whole implementation is SQL that only Postgres runs -
the `vector` type, the `<=>` cosine-distance operator, `ON CONFLICT` upsert and
JSONB round-tripping. A mocked version would assert that the mock works.

CI provides a server via the `pgvector/pgvector` service container (see the
`pgvector-store` job in .github/workflows/ci.yml). Locally:

    docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16
    TEST_DATABASE_URL=postgresql+psycopg2://postgres:pw@localhost:5432/postgres \\
        pytest tests/test_pgvector_store.py
"""
from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to a PostgreSQL server with the pgvector extension",
)

DIM = 8


def _vec(*values: float) -> list[float]:
    """Pad a short vector out to the column width."""
    padded = list(values) + [0.0] * (DIM - len(values))
    return padded[:DIM]


@pytest.fixture()
def store(monkeypatch):
    """A PgVectorStore on an isolated table, torn down afterwards."""
    import app.core.config as config_module
    import app.db.session as session_module
    import app.services.vector_store as vector_store_module
    from sqlalchemy import create_engine, text

    engine = create_engine(TEST_DATABASE_URL, future=True)
    monkeypatch.setattr(session_module, "engine", engine)

    settings = config_module.get_settings()
    monkeypatch.setattr(settings, "EMBEDDING_DIM", DIM, raising=False)
    monkeypatch.setattr(vector_store_module, "settings", settings)

    table = "chunk_embeddings_pytest"
    monkeypatch.setattr(vector_store_module.PgVectorStore, "_TABLE", table)

    instance = vector_store_module.PgVectorStore()
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table}"))
    try:
        yield instance
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()


def _record(chunk_id: str, document_id: str, text_value: str, embedding: list[float]):
    from app.services.vector_store import VectorRecord

    return VectorRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text_value,
        embedding=embedding,
        metadata={"document_id": document_id},
    )


def test_starts_empty(store) -> None:
    assert store.count() == 0


def test_upsert_then_count(store) -> None:
    store.upsert(
        [
            _record("c1", "doc-a", "first", _vec(1, 0, 0)),
            _record("c2", "doc-b", "second", _vec(0, 1, 0)),
        ]
    )
    assert store.count() == 2


def test_upsert_of_nothing_is_a_noop(store) -> None:
    store.upsert([])
    assert store.count() == 0


def test_query_ranks_by_cosine_similarity(store) -> None:
    store.upsert(
        [
            _record("near", "doc-near", "near", _vec(1, 0, 0)),
            _record("mid", "doc-mid", "mid", _vec(1, 1, 0)),
            _record("far", "doc-far", "far", _vec(0, 1, 0)),
        ]
    )
    hits = store.query(_vec(1, 0, 0), top_k=3)
    assert [hit.chunk_id for hit in hits] == ["near", "mid", "far"]


def test_query_returns_similarity_not_distance(store) -> None:
    """`<=>` yields distance; the platform's threshold expects similarity."""
    store.upsert([_record("identical", "doc-a", "identical", _vec(1, 0, 0))])
    hit = store.query(_vec(1, 0, 0), top_k=1)[0]
    assert hit.score == pytest.approx(1.0, abs=1e-6)


def test_orthogonal_vectors_score_zero(store) -> None:
    store.upsert([_record("ortho", "doc-a", "ortho", _vec(0, 1, 0))])
    hit = store.query(_vec(1, 0, 0), top_k=1)[0]
    assert hit.score == pytest.approx(0.0, abs=1e-6)


def test_query_respects_top_k(store) -> None:
    store.upsert([_record(f"c{i}", "doc-a", f"chunk {i}", _vec(1, i)) for i in range(5)])
    assert len(store.query(_vec(1, 0, 0), top_k=2)) == 2


def test_query_with_an_empty_embedding_returns_nothing(store) -> None:
    store.upsert([_record("c1", "doc-a", "first", _vec(1, 0, 0))])
    assert store.query([], top_k=3) == []


def test_metadata_round_trips_through_jsonb(store) -> None:
    store.upsert([_record("c1", "doc-a", "first", _vec(1, 0, 0))])
    assert store.query(_vec(1, 0, 0), top_k=1)[0].metadata == {"document_id": "doc-a"}


def test_upsert_updates_in_place_rather_than_duplicating(store) -> None:
    store.upsert([_record("c1", "doc-a", "original", _vec(1, 0, 0))])
    store.upsert([_record("c1", "doc-a", "revised", _vec(1, 0, 0))])
    assert store.count() == 1
    assert store.query(_vec(1, 0, 0), top_k=1)[0].text == "revised"


def test_delete_by_document_removes_only_that_document(store) -> None:
    store.upsert(
        [
            _record("c1", "doc-a", "keep", _vec(1, 0, 0)),
            _record("c2", "doc-b", "drop", _vec(0, 1, 0)),
            _record("c3", "doc-b", "drop too", _vec(0, 0, 1)),
        ]
    )
    store.delete_by_document("doc-b")
    assert store.count() == 1
    assert store.query(_vec(1, 0, 0), top_k=5)[0].document_id == "doc-a"


def test_vectors_survive_a_new_store_instance(store) -> None:
    """The reason this backend exists: a restart must not lose embeddings.

    `InMemoryVectorStore` returns 0 here, which is what silently breaks
    retrieval on any host that restarts.
    """
    from app.services.vector_store import PgVectorStore

    store.upsert([_record("c1", "doc-a", "persisted", _vec(1, 0, 0))])
    assert PgVectorStore().count() == 1


def test_rejects_a_non_postgres_database(monkeypatch) -> None:
    """Fail loudly rather than fall back to a store that forgets everything."""
    import app.db.session as session_module
    from sqlalchemy import create_engine

    from app.services.vector_store import PgVectorStore

    monkeypatch.setattr(session_module, "engine", create_engine("sqlite://"))
    with pytest.raises(RuntimeError, match="requires a PostgreSQL"):
        PgVectorStore()
