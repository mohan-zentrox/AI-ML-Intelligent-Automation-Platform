# Project Synapse

AI/ML Intelligent Automation Platform - document intelligence + governed,
citation-grounded RAG. This is a working foundation repo, not a mockup: the
ingestion -> embedding -> retrieval -> grounded answer -> human review ->
usage/cost tracking pipeline is real, runnable code with zero external
dependencies by default (no API keys, no network access, no Docker
required to run the backend).

See `docs/ARCHITECTURE.md` for the system design, `docs/API.md` for the
endpoint reference, `docs/TEAM.md` for the role roster/RBAC matrix, and
`docs/RESPONSIBLE_AI.md` for the grounding/citation/refusal/human-review
policy.

## Quick Start (zero dependencies - mock provider + in-memory vector store)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend comes up on `http://localhost:8000` (`/docs` for Swagger UI). On
first startup it creates a local SQLite DB (`synapse_local.db`) and seeds
the six `T6-*` role accounts from `docs/TEAM.md` (password `ChangeMe123!`
for all of them - local dev only).

Frontend:
```bash
cd frontend
npm install
npm run dev
```
Comes up on `http://localhost:5173`, talking to the backend at
`VITE_API_BASE_URL` (default `http://localhost:8000/api/v1`, see
`.env.example`).

## Docker Compose (Postgres + backend + frontend)

```bash
cp .env.example .env
docker compose up --build
```
ChromaDB and LiteLLM are **not** separate services here - they're
in-process, pluggable concerns (see below), not required infrastructure.
Postgres is used for relational storage; the vector store and LLM provider
default to the zero-dependency in-memory/mock implementations unless you
opt into `chroma`/`litellm` via env vars.

## Swapping in a Real LLM Provider

Everything talks to `app.services.llm_provider.LLMProvider` (an ABC), never
to a vendor SDK directly. To go live:

```env
LLM_PROVIDER=litellm
LITELLM_MODEL=gpt-4o-mini              # any litellm-supported model id
LITELLM_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...                  # or ANTHROPIC_API_KEY, etc.
```

No code changes needed - `get_llm_provider()` in
`backend/app/services/llm_provider.py` picks `LiteLLMProvider` based on
`LLM_PROVIDER` alone. The same pattern applies to the vector store
(`VECTOR_STORE_BACKEND=chroma` to switch from the in-memory fallback to a
persistent ChromaDB collection, once `chromadb` is installed).

## What's Fully Implemented (real, working code)

- **Auth & RBAC**: JWT login + scoped API key issuance/verification;
  `require_role()` gates every endpoint against the fixed role set
  (Admin/Workflow Builder/Reviewer/Analyst/API Consumer).
- **Document ingestion**: `POST /api/v1/documents` (multipart, .txt/.md or
  raw text) and `POST /api/v1/documents/text` (JSON) - real token-window
  chunking with overlap, real embeddings via the provider interface, real
  storage in the pluggable vector store + relational `chunks` table.
- **Grounded RAG Q&A**: `POST /api/v1/query` - real cosine-similarity
  retrieval, grounded prompt construction with numbered citations,
  transparent confidence scoring, and a documented insufficient-context
  refusal path when nothing clears `SIMILARITY_THRESHOLD`.
- **Human-in-the-loop review**: low-confidence answers are written to a
  `ReviewItem` queue; `GET /api/v1/review/queue` and
  `POST /api/v1/review/queue/{id}/decision` let a Reviewer/Admin
  approve/edit/reject with a mandatory rationale, feeding a `feedback`
  table for future eval-dataset building.
- **Usage/cost tracking**: every provider call logs tokens, cost (`$0` for
  the mock), and latency; `GET /api/v1/analytics/usage` aggregates by day
  and by user.
- **Frontend**: real React+TS+Tailwind pages (Login, Upload, Chat,
  ReviewQueue, UsageDashboard) wired to the live API via
  `frontend/src/api/client.ts` - not static mockups.

## What's Scaffolded (documented TODOs, no logic)

All under `backend/app/scaffold/`, each with FRD-section references:
- `parsers.py` - PDF / OCR / DOCX / email ingestion
- `workflow_builder.py` - no-code workflow DAG builder
- `classification.py` - automated document classification
- `field_extraction.py` - structured field extraction
- `promptfoo/promptfooconfig.yaml` - CI-gated RAG eval suite (config
  present, test fixtures empty, **not** wired into `.github/workflows/ci.yml`
  yet - that's the next step once real fixtures exist)

## Verification (what was actually run in this environment)

**This sandbox has no Python, Node.js, or Git installed** (confirmed via
`python`/`py`/`node`/`git` all resolving to nothing, aside from the Windows
Store app-execution-alias stub for `python`). As a result:

- `pytest` was **not executed** here. The full suite in `backend/tests/`
  was written and hand-reviewed for correctness against the mock
  provider + in-memory vector store path (the zero-external-dependency
  path), including exact arithmetic checks for chunk overlap and cosine
  similarity ranking, and monkeypatched threshold values (via pytest's
  `monkeypatch`, auto-restoring) so the low-confidence-review and
  insufficient-context-refusal tests don't depend on incidental hash
  collisions. **The dev team should run `cd backend && pip install -r
  requirements.txt && pytest -v` as the first step after cloning**, and
  treat any failures found there as real bugs to fix, not sandbox
  artifacts.
- `chromadb` was never installed or exercised here either; the in-memory
  fallback (`InMemoryVectorStore`) is what the test suite is written
  against, and it's what `VECTOR_STORE_BACKEND` defaults to.
- `npm install` / `npm run build` / `npm run lint` were **not executed**;
  the frontend was hand-reviewed for TypeScript/JSX correctness (import
  paths, prop types, hook usage) but not type-checked or bundled here.
- `git init`/`commit` were **not executed** - no `git` binary is present in
  this sandbox. The repo is left as a plain directory tree; initialize it
  with:
  ```bash
  git init -b main
  git config user.name "Zentrox Engineering"
  git config user.email "engineering@zentroxglobaltechnologies.com"
  git add -A
  git commit -m "Initial commit: Project Synapse foundation - document ingestion, grounded RAG Q&A, human review queue, usage/cost tracking"
  ```

## Repository Layout

```
backend/app/
  core/        config, security (JWT/API keys/roles), FastAPI deps (RBAC)
  db/          SQLAlchemy session + declarative base + seed data
  models/      User, ApiKey, Document, Chunk, QueryLog, ReviewItem, Feedback, UsageLog
  schemas/     Pydantic request/response models
  api/v1/      auth, documents, query, review, analytics routers
  services/    chunking, llm_provider (ABC+Mock+LiteLLM), vector_store (ABC+InMemory+Chroma), rag, ingestion
  scaffold/    documented, unimplemented extension points (see above)
backend/alembic/   migration environment + initial schema migration
backend/tests/     pytest suite (service-layer + API smoke tests)
frontend/src/      React+TS+Tailwind SPA (pages, api client, auth store)
docs/              architecture, API reference, team/RBAC, responsible AI policy
.github/workflows/ CI: lint + pytest + container build
```
