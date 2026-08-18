# Project Synapse - Architecture

## Overview

Project Synapse is a document-intelligence + governed RAG platform. The
foundation repo implements one full vertical slice end to end:

```
 Upload (text/.txt/.md)
        |
        v
 POST /api/v1/documents  --------->  chunk_text() ---> LLMProvider.embed() ---> VectorStoreRepository.upsert()
        |                                                                              |
        |                                                                              v
 POST /api/v1/query  ---> LLMProvider.embed(question) ---> VectorStoreRepository.query() (cosine top-k)
        |                                                                              |
        |            <---------------------------------------------------------------- 
        v
   threshold check -> grounded prompt -> LLMProvider.complete() -> answer + citations + confidence
        |
        +--> UsageLog (tokens, cost, latency)
        +--> if confidence < threshold: ReviewItem (pending) -> reviewer decision -> Feedback row
```

## Component Map

| Layer | Location | Notes |
|---|---|---|
| API | `backend/app/api/v1/*.py` | FastAPI routers, one file per resource |
| Auth/RBAC | `backend/app/core/security.py`, `backend/app/core/deps.py` | JWT + scoped API keys, `require_role()` dependency |
| Domain services | `backend/app/services/*.py` | `chunking.py`, `llm_provider.py`, `vector_store.py`, `rag.py`, `ingestion.py` |
| Persistence | `backend/app/models/*.py`, `backend/app/db/*.py` | SQLAlchemy 2.0 models, Alembic migrations |
| Frontend | `frontend/src/*` | React + TS + Tailwind SPA, thin `api/client.ts` wrapper |
| Scaffolds | `backend/app/scaffold/*` | Documented, unimplemented extension points (see below) |

## Pluggable Provider Pattern

Two seams are designed for zero-dependency local/offline operation by
default, with a config-only switch to real infrastructure:

1. **LLM/embedding provider** (`backend/app/services/llm_provider.py`)
   - `LLMProvider` ABC: `embed()`, `complete()`.
   - `MockProvider` (default, `LLM_PROVIDER=mock`): deterministic hashing
     bag-of-words embeddings + a template-based extractive "LLM" that only
     ever echoes/cites the retrieved context. Zero network calls, zero cost.
   - `LiteLLMProvider` (`LLM_PROVIDER=litellm`): thin adapter over the
     `litellm` package for unified OpenAI/Anthropic/Azure/etc. access with
     routing, fallback (`LITELLM_FALLBACK_MODELS`), and cost capture.
   - Selection: `app.services.llm_provider.get_llm_provider()`, driven
     entirely by `settings.LLM_PROVIDER`.

2. **Vector store** (`backend/app/services/vector_store.py`)
   - `VectorStoreRepository` ABC: `upsert()`, `query()`, `delete_by_document()`, `count()`.
   - `InMemoryVectorStore` (default, `VECTOR_STORE_BACKEND=inmemory`): pure
     Python cosine similarity, zero dependencies.
   - `ChromaVectorStore` (`VECTOR_STORE_BACKEND=chroma`): persistent
     ChromaDB collection. If the `chromadb` package is not importable (e.g.
     an offline sandbox), `get_vector_store()` automatically and silently
     falls back to `InMemoryVectorStore` so the rest of the application is
     unaffected.

Neither `app/services/rag.py` nor any API route imports a concrete
provider/store class directly - only the ABCs and the two factory
functions, which is what makes both seams genuinely swappable.

## Grounding, Refusal & Review (see also docs/RESPONSIBLE_AI.md)

`app/services/rag.py::answer_question()`:
1. Embeds the question.
2. Retrieves top-k chunks by cosine similarity.
3. Drops any chunk below `SIMILARITY_THRESHOLD`; if none remain, returns
   the documented insufficient-context refusal instead of calling the LLM.
4. Otherwise builds a numbered, citation-bearing grounded prompt and calls
   the LLM provider.
5. Computes a transparent confidence score from retrieval strength.
6. Logs usage (tokens/cost/latency) for every provider call.
7. If confidence < `REVIEW_CONFIDENCE_THRESHOLD`, writes a `ReviewItem`
   (status=pending) for human triage; reviewer decisions are captured to
   `feedback` for future eval-dataset construction.

## What's Scaffolded (Not Implemented)

See `backend/app/scaffold/` - each file has FRD-section-referenced TODOs,
no logic:
- `parsers.py` - OCR of scanned PDFs / email ingestion (PDF and DOCX are
  implemented - see `backend/app/services/parsers.py`)
- `workflow_builder.py` - no-code workflow DAG builder
- `classification.py` - automated document classification
- `field_extraction.py` - structured field extraction
- `promptfoo/promptfooconfig.yaml` - CI-gated eval suite (not wired into CI yet)
