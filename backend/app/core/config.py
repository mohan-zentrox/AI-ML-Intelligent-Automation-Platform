"""
Application configuration.

Project Synapse - AI/ML Intelligent Automation Platform
Reference: SRS section "Configuration Management", FRD section "Environment Parity"

All configuration is sourced from environment variables (with sane local-dev
defaults) via pydantic-settings so that the same container image can be
promoted from dev -> staging -> prod without code changes.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General ---
    APP_NAME: str = "Project Synapse"
    ENVIRONMENT: str = "local"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # --- Security / Auth ---
    # NOTE: default is only for local dev bootstrap. Override in every real
    # deployment environment.
    SECRET_KEY: str = "dev-only-insecure-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # --- Database ---
    DATABASE_URL: str = "sqlite:///./synapse_local.db"

    # --- Vector store ---
    # "chroma"   -> persistent ChromaDB collection (requires chromadb package)
    # "inmemory" -> pure-python cosine-similarity fallback, zero deps
    VECTOR_STORE_BACKEND: Literal["chroma", "inmemory"] = "inmemory"
    CHROMA_PERSIST_DIR: str = "./chroma_data"
    CHROMA_COLLECTION_NAME: str = "synapse_chunks"

    # --- LLM / embedding provider ---
    # "mock"     -> deterministic local provider, zero external calls, zero cost
    # "litellm"  -> real multi-provider routing via LiteLLM (needs API keys)
    LLM_PROVIDER: Literal["mock", "litellm"] = "mock"
    LITELLM_MODEL: str = "gpt-4o-mini"
    LITELLM_EMBEDDING_MODEL: str = "text-embedding-3-small"
    # Comma separated fallback chain for LiteLLM routing, e.g.
    # "gpt-4o-mini,claude-3-5-haiku-20241022"
    LITELLM_FALLBACK_MODELS: str = ""

    # --- RAG behaviour ---
    CHUNK_SIZE_TOKENS: int = 200
    CHUNK_OVERLAP_TOKENS: int = 40
    RETRIEVAL_TOP_K: int = 4
    # Below this cosine-similarity score a retrieved chunk is not considered
    # trustworthy grounding evidence.
    SIMILARITY_THRESHOLD: float = 0.15
    # Below this answer confidence score, the answer is routed to the human
    # review queue instead of (or in addition to) being returned directly.
    REVIEW_CONFIDENCE_THRESHOLD: float = 0.55

    # --- Document classification (FRD 7) ---
    # Auto-classify every ingested document into the taxonomy defined in
    # app/services/classification.py. Disable to ingest without spending a
    # provider call per document.
    CLASSIFICATION_ENABLED: bool = True
    # Only the first N characters are sent to the classifier: category signal
    # is concentrated at the top of a document, and this bounds cost/latency
    # to something predictable regardless of document size.
    CLASSIFICATION_SAMPLE_CHARS: int = 4000
    # Below this classification confidence the label is not trusted for
    # downstream routing and the document is queued for human confirmation.
    CLASSIFICATION_REVIEW_THRESHOLD: float = 0.55

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
