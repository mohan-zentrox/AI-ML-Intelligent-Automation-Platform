"""
Project Synapse backend entrypoint.

Run locally with:
    uvicorn app.main:app --reload --app-dir backend
or from within backend/:
    uvicorn app.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import analytics, auth, documents, query, review
from app.core.config import get_settings
from app.db.session import init_db, seed_reference_data

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Project Synapse - AI/ML Intelligent Automation Platform. "
        "Document intelligence + governed, grounded RAG."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # Dev/test convenience: create tables + seed the fixed T6-* roster if
    # missing. Production deployments should run `alembic upgrade head`
    # ahead of time instead (init_db here is a safe no-op if tables exist).
    init_db()
    seed_reference_data()


@app.get("/health", tags=["health"])
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "llm_provider": settings.LLM_PROVIDER,
        "vector_store_backend": settings.VECTOR_STORE_BACKEND,
    }


app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
app.include_router(query.router, prefix=settings.API_V1_PREFIX)
app.include_router(review.router, prefix=settings.API_V1_PREFIX)
app.include_router(analytics.router, prefix=settings.API_V1_PREFIX)
