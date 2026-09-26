"""
Project Synapse backend entrypoint.

Run locally with:
    uvicorn app.main:app --reload --app-dir backend
or from within backend/:
    uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import analytics, auth, documents, query, review
from app.core.config import get_settings
from app.db.session import SessionLocal, init_db, seed_reference_data

settings = get_settings()
logger = logging.getLogger(__name__)


def _warn_if_vector_store_is_stale() -> None:
    """Warn when documents exist relationally but the vector store is empty.

    `VECTOR_STORE_BACKEND=inmemory` keeps embeddings in process memory, so a
    restart drops every vector while the `documents` and `chunks` rows survive
    in the database. The two stores then disagree silently: the UI lists the
    documents as ingested, but every query refuses with "no retrieved chunk
    cleared the similarity threshold" because there is nothing left to
    retrieve. That reads like a broken retriever rather than lost state, so say
    it plainly at startup instead of leaving it to be rediscovered.

    Anything that restarts - a container redeploy, a free-tier host waking from
    idle - hits this, which is why it matters beyond local development.
    """
    try:
        from app.models.chunk import Chunk
        from app.services.vector_store import get_vector_store

        with SessionLocal() as db:
            relational_chunks = db.query(Chunk).count()
        vector_chunks = get_vector_store().count()
    except Exception:  # never block startup on a diagnostic
        logger.debug("Vector-store staleness check failed", exc_info=True)
        return

    if relational_chunks and not vector_chunks:
        logger.warning(
            "Vector store is EMPTY but the database holds %d chunk(s). Retrieval will "
            "refuse every question until those documents are re-ingested. This is the "
            "expected consequence of VECTOR_STORE_BACKEND=%s, which does not survive a "
            "restart - use a persistent backend for any environment that restarts.",
            relational_chunks,
            settings.VECTOR_STORE_BACKEND,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup/shutdown hook (replaces the deprecated @app.on_event).

    `init_db()` is a dev/test convenience and a no-op when the tables already
    exist; deployments should still run `alembic upgrade head` so schema
    changes are versioned rather than implicit.

    Demo-user seeding is gated on `should_seed_demo_users` (local-only unless
    explicitly overridden) because the seed password is published in
    docs/TEAM.md - seeding a reachable environment would publish an admin
    login along with it.
    """
    init_db()
    _warn_if_vector_store_is_stale()
    if settings.should_seed_demo_users:
        seed_reference_data()
        logger.warning(
            "Seeded the docs/TEAM.md demo accounts with their published default "
            "password (ENVIRONMENT=%s). Never do this in an environment that is "
            "reachable by anyone you don't trust.",
            settings.ENVIRONMENT,
        )
    else:
        logger.info(
            "Skipped demo-user seeding (ENVIRONMENT=%s). Create real users "
            "explicitly instead.",
            settings.ENVIRONMENT,
        )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Project Synapse - AI/ML Intelligent Automation Platform. "
        "Document intelligence + governed, grounded RAG."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health() -> dict:
    """Liveness probe plus the two numbers that explain most retrieval issues.

    `indexed_chunks` (vector store) and `stored_chunks` (database) should track
    each other. `stored_chunks > 0` with `indexed_chunks == 0` means the vector
    store was lost on restart and every query will refuse - see
    `_warn_if_vector_store_is_stale`.
    """
    from app.models.chunk import Chunk
    from app.services.vector_store import get_vector_store

    payload = {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "llm_provider": settings.LLM_PROVIDER,
        "vector_store_backend": settings.VECTOR_STORE_BACKEND,
    }
    try:
        with SessionLocal() as db:
            payload["stored_chunks"] = db.query(Chunk).count()
        payload["indexed_chunks"] = get_vector_store().count()
        payload["retrieval_ready"] = not (
            payload["stored_chunks"] > 0 and payload["indexed_chunks"] == 0
        )
    except Exception:  # a probe must not 500 just because a count failed
        logger.debug("Health chunk counts unavailable", exc_info=True)
    return payload


app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
app.include_router(query.router, prefix=settings.API_V1_PREFIX)
app.include_router(review.router, prefix=settings.API_V1_PREFIX)
app.include_router(analytics.router, prefix=settings.API_V1_PREFIX)
