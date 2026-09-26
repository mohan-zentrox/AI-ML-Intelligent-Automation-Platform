"""
Application configuration.

Project Synapse - AI/ML Intelligent Automation Platform
Reference: SRS section "Configuration Management", FRD section "Environment Parity"

All configuration is sourced from environment variables (with sane local-dev
defaults) via pydantic-settings so that the same container image can be
promoted from dev -> staging -> prod without code changes.
"""
import json
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The placeholder SECRET_KEY shipped for local bootstrap. It is public (it is
# in this file, in .env.example, and in git history), so it is treated as a
# sentinel meaning "nobody configured a real key" rather than as a usable
# secret - see `_reject_insecure_production_config` below.
DEV_SECRET_KEY = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General ---
    APP_NAME: str = "Project Synapse"
    # "local" unlocks developer conveniences (demo-user seeding, the
    # placeholder SECRET_KEY). Any other value is treated as a real
    # deployment and is held to the checks in
    # `_reject_insecure_production_config`.
    ENVIRONMENT: str = "local"
    API_V1_PREFIX: str = "/api/v1"
    # Currently informational only - nothing reads it - but defaulted off so
    # it can never become a footgun if something starts honouring it later.
    DEBUG: bool = False

    # --- Security / Auth ---
    # Signs JWTs *and* HMACs the stored API-key hashes, so a known value means
    # anyone can mint an admin token. Startup fails when this is still the
    # placeholder and ENVIRONMENT != "local".
    SECRET_KEY: str = DEV_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # --- Database ---
    DATABASE_URL: str = "sqlite:///./synapse_local.db"

    # --- Vector store ---
    # "pgvector" -> embeddings in the same Postgres that holds the documents.
    #               The only backend that survives a restart without a mounted
    #               disk, so this is the one to use on managed/free hosting.
    # "chroma"   -> persistent ChromaDB collection (needs the chromadb package
    #               and a persistent directory)
    # "inmemory" -> pure-python cosine similarity, zero deps, and LOSES every
    #               embedding on restart - fine for local dev and tests only
    VECTOR_STORE_BACKEND: Literal["pgvector", "chroma", "inmemory"] = "inmemory"
    # Dimensionality of the active embedding model; sizes the pgvector column.
    # Must match the provider - the mock provider emits 256, OpenAI
    # text-embedding-3-small emits 1536. Changing this once documents exist
    # means re-ingesting them.
    EMBEDDING_DIM: int = 256
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

    # --- Demo data ---
    # Seeds the six T6-* roster accounts from docs/TEAM.md with a shared,
    # publicly-documented password. Leave unset: it then resolves to True only
    # when ENVIRONMENT == "local" (see `should_seed_demo_users`). Setting it to
    # True explicitly in a deployed environment creates a known-credential
    # admin account, so do that only for a throwaway demo you intend to be
    # open.
    SEED_DEMO_USERS: bool | None = None

    # --- CORS ---
    # Declared as a plain string, NOT list[str], on purpose.
    #
    # pydantic-settings JSON-decodes complex (list/dict) fields inside
    # EnvSettingsSource, *before* any field validator runs. So with a
    # `list[str]` annotation, `CORS_ORIGINS=https://a.example,https://b.example`
    # dies with an unhelpful `SettingsError: error parsing value for field` at
    # import time and a `mode="before"` validator never gets a chance to split
    # it. (pydantic-settings only gained `NoDecode` for this in 2.6; this
    # project pins 2.3.4.)
    #
    # Keeping the raw value a string and parsing it in `cors_origins` below
    # means every input path behaves identically - real env var, .env file, or
    # a direct kwarg - and a comma-separated list is what anyone typing this
    # into a hosting dashboard will naturally write:
    #     CORS_ORIGINS=https://synapse.pages.dev,https://www.example.com
    # A JSON array is still accepted.
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        """`CORS_ORIGINS` parsed into a list of origins."""
        text = self.CORS_ORIGINS.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"CORS_ORIGINS looks like JSON but does not parse: {exc}") from exc
            if not isinstance(decoded, list):
                raise ValueError("CORS_ORIGINS JSON must be an array of origin strings")
            return [str(origin).strip() for origin in decoded if str(origin).strip()]
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @property
    def is_local(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "local"

    @property
    def should_seed_demo_users(self) -> bool:
        """Whether to create the docs/TEAM.md demo accounts on startup.

        Defaults to local-only rather than always-on: the seed password is
        published in docs/TEAM.md and README.md, so seeding a deployed
        environment hands an admin login to anyone who has read the repo.
        """
        if self.SEED_DEMO_USERS is None:
            return self.is_local
        return self.SEED_DEMO_USERS

    @model_validator(mode="after")
    def _reject_insecure_production_config(self) -> "Settings":
        """Fail fast instead of booting a deployment with known credentials.

        Both of these are silent, total auth bypasses rather than degraded
        modes, which is why this raises at startup rather than logging a
        warning: a warning in a container log is not something anyone sees
        before the service is reachable.
        """
        if self.is_local:
            return self
        if self.SECRET_KEY == DEV_SECRET_KEY:
            raise ValueError(
                f"SECRET_KEY is still the public placeholder but ENVIRONMENT="
                f"{self.ENVIRONMENT!r}. It signs JWTs and HMACs API-key hashes, "
                "so leaving it at the default lets anyone forge an admin token. "
                "Set SECRET_KEY to a random secret "
                "(`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
            )
        if self.SEED_DEMO_USERS:
            raise ValueError(
                f"SEED_DEMO_USERS=true with ENVIRONMENT={self.ENVIRONMENT!r} would create "
                "the docs/TEAM.md demo accounts, whose shared password is published in "
                "this repo, including an admin. Unset SEED_DEMO_USERS (it then seeds only "
                "when ENVIRONMENT=local) or set it to false."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
