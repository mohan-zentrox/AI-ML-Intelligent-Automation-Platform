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

import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.config import get_settings

settings = get_settings()


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


_store_instance: VectorStoreRepository | None = None


def get_vector_store() -> VectorStoreRepository:
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    if settings.VECTOR_STORE_BACKEND == "chroma":
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
