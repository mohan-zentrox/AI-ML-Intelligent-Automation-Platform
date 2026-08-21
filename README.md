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

## Verification (what was actually run in this environment)

Python 3.11, Node 22, and git are all available here, so the following were
executed rather than hand-reviewed:

- `pytest` - **86 passed** (`backend/.venv`, lean install: fastapi,
  sqlalchemy, passlib/bcrypt, python-jose, python-multipart, httpx, pytest,
  ruff, pypdf, python-docx, alembic). This is the zero-external-dependency
  path: `LLM_PROVIDER=mock`, `VECTOR_STORE_BACKEND=inmemory`, SQLite
  in-memory.
- `alembic upgrade head`, `alembic downgrade base`, and re-upgrade against a
  scratch SQLite file - both migrations (`0001`, `0002`) run clean in both
  directions.
- `ruff check app tests` - clean.
- `npm install && npm run lint && npm run build` - eslint clean, `tsc -b`
  clean, vite production bundle built.

Not exercised here:

- `chromadb` and `litellm` were not installed (both are optional at runtime;
  the app falls back to `InMemoryVectorStore` / `MockProvider`). The Docker
  images and Postgres path were likewise not built or run.
- OCR of scanned PDFs and email ingestion are unimplemented by design - see
  `backend/app/scaffold/parsers.py`.

PDF/DOCX test fixtures are **built in-process** by
`backend/tests/document_fixtures.py` (a real PDF byte stream with a proper
xref table; a real .docx zip package), so the suite needs no checked-in
binaries and no network.

## Repository Layout

```
backend/app/
  core/        config, security (JWT/API keys/roles), FastAPI deps (RBAC)
  db/          SQLAlchemy session + declarative base + seed data
  models/      User, ApiKey, Document, Chunk, QueryLog, ReviewItem, Feedback, UsageLog
  schemas/     Pydantic request/response models
  api/v1/      auth, documents, query, review, analytics routers
  services/    chunking, parsers (PDF/DOCX/text), classification (taxonomy + constrained-label prompt), llm_provider (ABC+Mock+LiteLLM), vector_store (ABC+InMemory+Chroma), rag, ingestion
  scaffold/    documented, unimplemented extension points (see above)
backend/alembic/   migration environment + initial schema migration
backend/tests/     pytest suite (service-layer + API smoke tests)
frontend/src/      React+TS+Tailwind SPA (pages, api client, auth store)
docs/              architecture, API reference, team/RBAC, responsible AI policy
.github/workflows/ CI: lint + pytest + container build
```
