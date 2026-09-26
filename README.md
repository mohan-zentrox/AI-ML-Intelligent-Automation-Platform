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
for all of them).

Seeding is **gated on `ENVIRONMENT=local`** (the default). Those credentials
are published in this repo, so any other `ENVIRONMENT` value skips seeding
and you create real users yourself; setting `SEED_DEMO_USERS=true` outside
`local` is rejected at startup rather than silently obeyed.

`requirements.txt` is the core set only. The optional provider backends
(`chromadb`, `litellm`) live in `requirements-optional.txt` and are needed
only if you switch away from the defaults:

```bash
pip install -r requirements.txt -r requirements-optional.txt
```

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

Install `requirements-optional.txt` first (that is where `litellm` is
pinned). No code changes needed - `get_llm_provider()` in
`backend/app/services/llm_provider.py` picks `LiteLLMProvider` based on
`LLM_PROVIDER` alone. The same pattern applies to the vector store
(`VECTOR_STORE_BACKEND=chroma` to switch from the in-memory fallback to a
persistent ChromaDB collection, once `chromadb` is installed).

## What's Fully Implemented (real, working code)

- **Auth & RBAC**: JWT login + scoped API key issuance/verification;
  `require_role()` gates every endpoint against the fixed role set
  (Admin/Workflow Builder/Reviewer/Analyst/API Consumer).
- **Document ingestion**: `POST /api/v1/documents` (multipart, .txt/.md/
  .pdf/.docx or raw text) and `POST /api/v1/documents/text` (JSON) - real
  token-window chunking with overlap, real embeddings via the provider
  interface, real storage in the pluggable vector store + relational
  `chunks` table.
- **Multi-format parsing** (FRD 4.2): `backend/app/services/parsers.py`
  extracts the PDF text layer via `pypdf` and DOCX paragraphs + table cells
  via `python-docx`, dispatching on file extension through a `PARSERS`
  registry - adding a format is a one-line registration, no router change.
  DOCX degrades to a stdlib zipfile/ElementTree reader when `python-docx`
  isn't installed, so it keeps working with zero external dependencies;
  PDF returns a 503 (not a 500) when `pypdf` is absent. Pages with no text
  layer are reported in `ParsedDocument.metadata["empty_pages"]` as the
  hand-off signal for OCR, which is still scaffolded (FRD 4.2.2).
- **Automated document classification** (FRD 7): every ingested document is
  tagged with exactly one label from a versioned taxonomy
  (`backend/app/services/classification.py`) via a constrained-label prompt
  over the *same* `LLMProvider` seam RAG uses - no second model stack. The
  taxonomy is a one-entry-per-category registry, served to clients at
  `GET /api/v1/documents/taxonomy` so label pickers can't drift, and
  `TAXONOMY_VERSION` is stamped on every stored label so stale
  classifications are findable and re-runnable via
  `POST /api/v1/documents/{id}/reclassify`. `GET /api/v1/documents?label=`
  filters by category. Classification never fails an ingest: an
  off-taxonomy label, an unparseable response, or a provider outage all
  degrade to `unknown`/0.0 confidence and route to a human.
- **Grounded RAG Q&A**: `POST /api/v1/query` - real cosine-similarity
  retrieval, grounded prompt construction with numbered citations,
  transparent confidence scoring, and a documented insufficient-context
  refusal path when nothing clears `SIMILARITY_THRESHOLD`.
- **Human-in-the-loop review**: low-confidence answers *and* low-confidence
  classifications are written to one `ReviewItem` queue (`item_type`
  distinguishes them); `GET /api/v1/review/queue` and
  `POST /api/v1/review/queue/{id}/decision` let a Reviewer/Admin
  approve/edit/reject with a mandatory rationale, feeding a `feedback`
  table for future eval-dataset building. A resolved classification is
  written back onto the document (`confirmed`/`corrected`/`rejected`), so
  the queue actually governs what downstream routing reads rather than
  just recording opinions - a rejected label is cleared, not left in place.
- **Usage/cost tracking**: every provider call logs tokens, cost (`$0` for
  the mock), and latency; `GET /api/v1/analytics/usage` aggregates by day
  and by user.
- **Frontend**: real React+TS+Tailwind pages (Login, Upload, Chat,
  ReviewQueue, UsageDashboard) wired to the live API via
  `frontend/src/api/client.ts` - not static mockups. The Upload page has
  paste-text and file-upload modes, the latter posting real multipart
  `FormData` (auth headers only, so the browser sets the boundary).

## What's Scaffolded (documented TODOs, no logic)

All under `backend/app/scaffold/`, each with FRD-section references:
- `parsers.py` - OCR of scanned PDFs / email ingestion (PDF and DOCX are
  implemented - see `backend/app/services/parsers.py`)
- `workflow_builder.py` - no-code workflow DAG builder
- `field_extraction.py` - structured field extraction (would key its
  per-category schemas off the taxonomy in
  `backend/app/services/classification.py`)
- `promptfoo/promptfooconfig.yaml` - CI-gated RAG eval suite (config
  present, test fixtures empty, **not** wired into `.github/workflows/ci.yml`
  yet - that's the next step once real fixtures exist)

## Deployment Notes

Full step-by-step runbook: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**
(Cloudflare Pages + Render + Neon, all free tier). `render.yaml` in the repo
root is a Render Blueprint for the backend.

Three things bite when moving off localhost:

1. **`VITE_API_BASE_URL` is build-time, not runtime.** Vite inlines `VITE_*`
   into the JS bundle during `npm run build`, so setting it on a running
   container has no effect. Pass it as a Docker build arg (already wired
   through `docker-compose.yml`):
   ```bash
   docker compose build --build-arg VITE_API_BASE_URL=https://your-api.example.com/api/v1
   ```
2. **`SECRET_KEY` and `CORS_ORIGINS` must both be set.** The app refuses to
   start with the placeholder `SECRET_KEY` unless `ENVIRONMENT=local`, and a
   deployed frontend is on a different origin than the API, so it has to be
   listed in `CORS_ORIGINS` or every browser request fails preflight.

The backend honours `$PORT` (falling back to 8000), which is how Render, Fly,
Cloud Run and Hugging Face Spaces assign a listen port.

3. **Use `VECTOR_STORE_BACKEND=pgvector`.** The default `inmemory` backend
   loses every embedding on restart, and `chroma` needs a persistent disk that
   most free tiers do not offer. Either way the database keeps the document and
   chunk rows, so the UI goes on listing documents as ingested while every
   query refuses - a silent failure rather than a loud one. `pgvector` keeps
   the embeddings in the same Postgres as the documents, so the two cannot
   drift apart:

   ```env
   DATABASE_URL=postgresql+psycopg2://...
   VECTOR_STORE_BACKEND=pgvector
   EMBEDDING_DIM=256          # 256 for the mock provider, 1536 for text-embedding-3-small
   ```

   It needs only the server-side `vector` extension (Neon, Supabase and RDS all
   ship it) - no extra Python package, since it uses raw SQL over the psycopg2
   driver already in `requirements.txt`. The extension, table and HNSW index
   are created on first use. `GET /health` reports `stored_chunks`,
   `indexed_chunks` and `retrieval_ready` so a mismatch is visible immediately.

## Verification (what was actually run in this environment)

Python 3.11, Node 22, and git are all available here, so the following were
executed rather than hand-reviewed:

- `pip install -r requirements.txt` - resolves clean, and
  `pip install --dry-run -r requirements.txt -r requirements-optional.txt`
  confirms the optional pins still co-resolve with the core ones.
- `pytest` - **116 passed, 13 skipped** (`backend/.venv`); the skips are the
  pgvector suite, which needs a Postgres server (see below). This is the
  zero-external-dependency path: `LLM_PROVIDER=mock`,
  `VECTOR_STORE_BACKEND=inmemory`, SQLite in-memory.
- `python -c "import app.main"` as a *first* import, plus a real
  `uvicorn` boot and a `/health` probe. Both are also enforced by the
  `backend-boots` CI job, because the test suite cannot catch a boot failure:
  `conftest.py` imports `app.db.base` before `app.main`, and that ordering
  hides import cycles.
- `alembic upgrade head`, `alembic downgrade base`, and re-upgrade against a
  scratch SQLite file - both migrations (`0001`, `0002`) run clean in both
  directions.
- `ruff check app tests` - clean.
- `PgVectorStore` against a real PostgreSQL 18 + pgvector 0.8.6 server
  (Neon): **13 passed**, covering cosine ranking, similarity-vs-distance
  conversion, in-place upsert, JSONB metadata round-trip, delete-by-document,
  and - the point of the backend - embeddings surviving a fresh process.
  `alembic upgrade head` was also run against that Postgres, which is the
  first time the non-SQLite path has been exercised at all.
- A full manual pass against the running stack: login, JWT + `X-API-Key` auth,
  the whole RBAC matrix in `docs/TEAM.md` (all 9 allow/deny cells), text +
  multipart PDF/DOCX ingestion, classification, grounded query, the refusal
  path, the review queue, a classification correction writing back to the
  document, and the usage dashboard.
- `npm ci && npm run lint && npm run build` - eslint clean, `tsc -b` clean,
  vite production bundle built.

Not exercised here:

- `chromadb` and `litellm` are resolved but not installed (both are optional
  at runtime; the app falls back to `InMemoryVectorStore` / `MockProvider`).
  The Docker images and the Postgres path were likewise not built or run.
- OCR of scanned PDFs and email ingestion are unimplemented by design - see
  `backend/app/scaffold/parsers.py`.

Known, accepted `npm audit` findings:

- `vite` / `esbuild` (1 high, 1 moderate) affect the **dev server only**. The
  shipped artifact is static files served by nginx, so it is not exposed. The
  advisory's fix is a Vite major bump, deferred deliberately.
- `react-router` open redirect (moderate) is **not reachable here**: every
  `navigate()` / `<Link to=>` target in `frontend/src` is a hardcoded literal,
  with no user-controlled input. The only patched version is a v6 -> v7 major,
  so it is tracked rather than force-upgraded. Re-evaluate if a redirect
  target ever becomes dynamic.

PDF/DOCX test fixtures are **built in-process** by
`backend/tests/document_fixtures.py` (a real PDF byte stream with a proper
xref table; a real .docx zip package), so the suite needs no checked-in
binaries and no network.

## Repository Layout

```
backend/app/
  core/        config (+ startup safety checks), security (JWT/API keys/roles), FastAPI deps (RBAC)
  db/          base_class (Base only) + base (model registry hub) + session/seed
  models/      User, ApiKey, Document, Chunk, QueryLog, ReviewItem, Feedback, UsageLog
  schemas/     Pydantic request/response models
  api/v1/      auth, documents, query, review, analytics routers
  services/    chunking, parsers (PDF/DOCX/text), classification (taxonomy + constrained-label prompt), llm_provider (ABC+Mock+LiteLLM), vector_store (ABC+InMemory+Chroma), rag, ingestion
  scaffold/    documented, unimplemented extension points (see above)
backend/alembic/   migration environment + initial schema migration
backend/tests/     pytest suite (service-layer + API smoke + startup-guard tests)
backend/requirements.txt          core dependencies
backend/requirements-optional.txt chromadb + litellm (opt-in backends)
frontend/nginx.conf               SPA history-mode fallback for the container
frontend/src/      React+TS+Tailwind SPA (pages, api client, auth store)
docs/              architecture, API reference, team/RBAC, responsible AI policy
.github/workflows/ CI: lint + pytest + container build
```
