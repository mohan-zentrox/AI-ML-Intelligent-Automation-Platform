"""
Pluggable vector store interface.

Reference: FRD section "Vector Store Abstraction" - ChromaDB is the intended
production backend, but the platform must degrade gracefully to a
zero-dependency in-process implementation when `chromadb` cannot be
installed (offline/sandboxed environments, some CI runners, etc.).

Both `ChromaVectorStore` and `InMemoryVectorStore` implement the same
`VectorStoreRepository` ABC, so app/services/rag.py and the documents API
never need to know which backend is active. Selection is driven by
`settings.VECTOR_STORE_BACKEND` (env var `VECTOR_STORE_BACKEND=chroma|inmemory`),
with an automatic fallback to `inmemory` if `chroma` is requested but the
`chromadb` package is not importable - this is exactly the scenario this
sandbox is in, and it is what backend/tests exercise.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    chunk_id: str
    document_id: str
    text: str
    embedding: list[float]
    metadata: dict = field(default_factory=dict)


@dataclass
class ScoredChunk:
    chunk_id: str
    document_id: str
    text: str
    score: float  # cosine similarity, higher is better
    metadata: dict = field(default_factory=dict)


class VectorStoreRepository(ABC):
    """Storage + similarity search for chunk embeddings."""

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None:
        ...

    @abstractmethod
    def query(self, embedding: list[float], top_k: int) -> list[ScoredChunk]:
        ...

    @abstractmethod
    def delete_by_document(self, document_id: str) -> None:
        ...

    @abstractmethod
    def count(self) -> int:
        ...


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore(VectorStoreRepository):
    """Pure-python cosine-similarity search. Zero external dependencies.

    Data lives in a process-local dict, so it does not survive a restart;
    that's an acceptable tradeoff for local dev / offline CI / the sandboxed
    environment this repo was scaffolded in. For a durable zero-dependency
    option beyond process lifetime, chunks are also persisted relationally
    in the `chunks` table (see app/models/chunk.py) and can be used to
    rebuild this index on startup.
    """

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}
        self._lock = threading.Lock()

    def upsert(self, records: list[VectorRecord]) -> None:
        with self._lock:
            for r in records:
                self._records[r.chunk_id] = r

    def query(self, embedding: list[float], top_k: int) -> list[ScoredChunk]:
        with self._lock:
            scored = [
                ScoredChunk(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    text=r.text,
                    score=_cosine_similarity(embedding, r.embedding),
                    metadata=r.metadata,
                )
                for r in self._records.values()
            ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def delete_by_document(self, document_id: str) -> None:
        with self._lock:
            to_delete = [cid for cid, r in self._records.items() if r.document_id == document_id]
            for cid in to_delete:
                del self._records[cid]

    def count(self) -> int:
        with self._lock:
            return len(self._records)


class ChromaVectorStore(VectorStoreRepository):
    """Persistent ChromaDB-backed implementation.

    Requires the `chromadb` package (see backend/requirements.txt). If it is
    not importable, `get_vector_store()` automatically falls back to
    `InMemoryVectorStore` - see below.
    """

    def __init__(self) -> None:
        import chromadb  # local import: only required when this backend is selected

        self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        self._collection = self._client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION_NAME
        )

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        self._collection.upsert(
            ids=[r.chunk_id for r in records],
            embeddings=[r.embedding for r in records],
            documents=[r.text for r in records],
            metadatas=[{"document_id": r.document_id, **r.metadata} for r in records],
        )

    def query(self, embedding: list[float], top_k: int) -> list[ScoredChunk]:
        if self._collection.count() == 0:
            return []
        result = self._collection.query(query_embeddings=[embedding], n_results=top_k)
        scored: list[ScoredChunk] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for cid, text, meta, dist in zip(ids, docs, metadatas, distances):
            # Chroma's default space is L2 distance; convert to a
            # similarity-like score in (0, 1] for a consistent contract with
            # InMemoryVectorStore's cosine similarity.
            similarity = 1.0 / (1.0 + dist)
            scored.append(
                ScoredChunk(
                    chunk_id=cid,
                    document_id=meta.get("document_id", ""),
                    text=text,
                    score=similarity,
                    metadata=meta,
                )
            )
        return scored

    def delete_by_document(self, document_id: str) -> None:
        self._collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return self._collection.count()



# --------------------------------------------------------------------------
# pgvector - persistent, and the only backend that survives a restart on a
# free host with no mounted disk.
# --------------------------------------------------------------------------


class PgVectorStore(VectorStoreRepository):
    """Similarity search in Postgres via the `pgvector` extension.

    Why this exists: `InMemoryVectorStore` loses every embedding when the
    process restarts, and `ChromaVectorStore` needs a persistent directory.
    Free hosting tiers restart constantly and mostly offer no disk, so both
    leave the relational rows and the vectors disagreeing - documents keep
    listing as ingested while every query refuses for lack of anything to
    retrieve. Keeping the vectors in the same Postgres that already holds the
    documents makes that divergence impossible by construction.

    Deliberately uses raw SQL with `::vector` casts rather than the `pgvector`
    Python package, so it needs nothing beyond the psycopg2 driver that is
    already a core dependency - only the server-side extension, which managed
    Postgres providers (Neon, Supabase, RDS) ship.

    Embeddings live in their own table rather than as a column on `chunks`, so
    enabling or dropping this backend never migrates application data.
    """

    name = "pgvector"

    _TABLE = "chunk_embeddings"

    def __init__(self) -> None:
        from app.db.session import engine

        if engine.dialect.name != "postgresql":
            raise RuntimeError(
                "VECTOR_STORE_BACKEND=pgvector requires a PostgreSQL DATABASE_URL, "
                f"but the configured database is {engine.dialect.name!r}. Use "
                "VECTOR_STORE_BACKEND=inmemory for local SQLite development."
            )
        self._engine = engine
        self._dim = settings.EMBEDDING_DIM
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the extension, table and indexes if absent.

        Done here rather than in an alembic migration on purpose: this table is
        derived state that only exists when this backend is selected, and a
        migration would force every deployment - including SQLite ones - to
        carry a pgvector-shaped schema it cannot create.
        """
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS "
                    + self._TABLE
                    + " ("
                    "chunk_id    TEXT PRIMARY KEY,"
                    "document_id TEXT NOT NULL,"
                    "text        TEXT NOT NULL,"
                    "embedding   vector(" + str(self._dim) + ") NOT NULL,"
                    "metadata    JSONB NOT NULL DEFAULT '{}'::jsonb"
                    ")"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS " + self._TABLE + "_document_id_idx ON "
                    + self._TABLE + " (document_id)"
                )
            )

        # HNSW over cosine distance, in its own transaction: Postgres still
        # answers queries by sequential scan without it, so a server build that
        # cannot create it must not take the whole backend down.
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS " + self._TABLE + "_embedding_idx ON "
                        + self._TABLE + " USING hnsw (embedding vector_cosine_ops)"
                    )
                )
        except Exception:  # pragma: no cover - depends on the server build
            logger.warning(
                "Could not create the HNSW index on %s; queries will fall back to a "
                "sequential scan, which is correct but slower.",
                self._TABLE,
                exc_info=True,
            )

    @staticmethod
    def _to_vector_literal(embedding: list[float]) -> str:
        """pgvector's text input format, e.g. "[0.1,0.2]"."""
        return "[" + ",".join(repr(float(value)) for value in embedding) + "]"

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        from sqlalchemy import text

        statement = text(
            "INSERT INTO " + self._TABLE + " (chunk_id, document_id, text, embedding, metadata) "
            "VALUES (:chunk_id, :document_id, :text, (:embedding)::vector, (:metadata)::jsonb) "
            "ON CONFLICT (chunk_id) DO UPDATE SET "
            "document_id = EXCLUDED.document_id, "
            "text = EXCLUDED.text, "
            "embedding = EXCLUDED.embedding, "
            "metadata = EXCLUDED.metadata"
        )
        with self._engine.begin() as conn:
            conn.execute(
                statement,
                [
                    {
                        "chunk_id": record.chunk_id,
                        "document_id": record.document_id,
                        "text": record.text,
                        "embedding": self._to_vector_literal(record.embedding),
                        "metadata": json.dumps(record.metadata or {}),
                    }
                    for record in records
                ],
            )

    def query(self, embedding: list[float], top_k: int) -> list[ScoredChunk]:
        if not embedding or top_k <= 0:
            return []
        from sqlalchemy import text

        # `<=>` is cosine DISTANCE; the rest of the platform (and
        # SIMILARITY_THRESHOLD) speaks cosine similarity, so convert in the
        # projection and keep the raw operator in ORDER BY, where the HNSW
        # index can actually be used.
        statement = text(
            "SELECT chunk_id, document_id, text, metadata, "
            "1 - (embedding <=> (:embedding)::vector) AS score "
            "FROM " + self._TABLE + " "
            "ORDER BY embedding <=> (:embedding)::vector "
            "LIMIT :top_k"
        )
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    statement,
                    {"embedding": self._to_vector_literal(embedding), "top_k": top_k},
                )
                .mappings()
                .all()
            )

        return [
            ScoredChunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                text=row["text"],
                score=float(row["score"]),
                metadata=row["metadata"] or {},
            )
            for row in rows
        ]

    def delete_by_document(self, document_id: str) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM " + self._TABLE + " WHERE document_id = :document_id"),
                {"document_id": document_id},
            )

    def count(self) -> int:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            return int(
                conn.execute(text("SELECT count(*) FROM " + self._TABLE)).scalar_one()
            )


_store_instance: VectorStoreRepository | None = None


def get_vector_store() -> VectorStoreRepository:
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    if settings.VECTOR_STORE_BACKEND == "pgvector":
        # No silent fallback here, unlike chroma below. Chroma degrading to
        # in-memory costs a local developer nothing, but pgvector is chosen
        # precisely because the data has to persist - quietly swapping in a
        # store that forgets everything on restart would turn a visible
        # misconfiguration into silent data loss.
        _store_instance = PgVectorStore()
    elif settings.VECTOR_STORE_BACKEND == "chroma":
        try:
            _store_instance = ChromaVectorStore()
        except ImportError:
            # Documented, graceful degradation: chromadb isn't installed in
            # this environment (e.g. offline sandbox) -> fall back so the
            # rest of the application keeps working unmodified.
            _store_instance = InMemoryVectorStore()
    else:
        _store_instance = InMemoryVectorStore()
    return _store_instance


def reset_vector_store() -> None:
    global _store_instance
    _store_instance = None
