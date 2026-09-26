# Project Synapse

**An AI/ML intelligent automation platform for document intelligence and
governed, citation-grounded question answering.**

You upload documents. Synapse parses them, sorts them into a category, splits
them into chunks, embeds those chunks, and indexes them. You then ask questions
in plain English and get back an answer that is **grounded only in your
documents**, with numbered citations pointing at the exact chunks it used. When
the system is not confident enough, it says so and routes the case to a human
instead of guessing — and every model call is logged with its token count,
latency and cost.

This is a working application, not a mockup or a prototype skeleton. It runs
with **no API keys, no network access, and no Docker** out of the box, because
the LLM provider and vector store are pluggable and both default to local,
deterministic implementations.

---

## Table of contents

- [What it does](#what-it-does)
- [Core ideas](#core-ideas)
- [Quick start](#quick-start)
- [Using the application](#using-the-application)
- [Using the API](#using-the-api)
- [Roles and permissions](#roles-and-permissions)
- [Configuration](#configuration)
- [Running with Docker Compose](#running-with-docker-compose)
- [Using a real LLM provider](#using-a-real-llm-provider)
- [Choosing a vector store](#choosing-a-vector-store)
- [Deployment](#deployment)
- [Testing](#testing)
- [What is built and what is not](#what-is-built-and-what-is-not)
- [Troubleshooting](#troubleshooting)
- [Repository layout](#repository-layout)

---

## What it does

```mermaid
flowchart LR
    A[Upload<br/>txt / md / pdf / docx] --> B[Parse<br/>text extraction]
    B --> C[Classify<br/>into taxonomy]
    C --> D[Chunk<br/>token windows]
    D --> E[Embed<br/>via LLM provider]
    E --> F[(Vector store)]
    G[Question] --> H[Retrieve<br/>cosine similarity]
    F --> H
    H --> I{Clears<br/>threshold?}
    I -- no --> J[Refuse<br/>insufficient context]
    I -- yes --> K[Grounded answer<br/>+ citations]
    K --> L{Confident?}
    C --> L
    L -- no --> M[Human review queue]
    M --> N[Reviewer decision<br/>writes back]
    style J fill:#fde,stroke:#c66
    style M fill:#ffd,stroke:#cc6
    style K fill:#dfd,stroke:#6c6
```

Every provider call along that path — embeddings, classification, answer
generation — writes a usage record, so cost is attributable per day and per
user.

## Core ideas

**Grounding over fluency.** The answer prompt contains only retrieved chunks.
If nothing retrieved clears `SIMILARITY_THRESHOLD`, the platform returns a
refusal and **never calls the LLM at all**. A confident-sounding wrong answer is
the failure mode this design exists to prevent.

**Citations are not decoration.** Every answer carries `citations[]` with the
document id, chunk id, similarity score and the snippet used. You can always
check what the answer was built from.

**Low confidence routes to a human.** Both a shaky answer and a shaky document
label land in **one** review queue, distinguished by `item_type`. A reviewer
approves, edits or rejects with a mandatory rationale — and for a classification
that decision is written back onto the document, so the queue governs what
downstream routing actually sees rather than just recording opinions.

**Nothing is hardcoded to a vendor.** Everything upstream talks to the
`LLMProvider` abstract base class, never to a vendor SDK. Swapping OpenAI,
Anthropic or Azure in is an environment variable, not a code change. The vector
store works the same way.

**Every category comes from one registry.** The classification taxonomy is
served to clients at `GET /documents/taxonomy` and stamped with a
`TAXONOMY_VERSION` on every stored label, so labels cannot drift between
frontend and backend, and stale classifications are findable and re-runnable.

---

## Quick start

**Requirements:** Python 3.11+ and Node 18+. Nothing else — no Docker, no
Postgres, no API keys.

### 1. Backend

```bash
cd backend
python -m venv .venv

.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend is on **http://localhost:8000** — interactive API docs at
**http://localhost:8000/docs**.

On first start it creates a local SQLite file (`synapse_local.db`) and seeds six
demo accounts.

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend is on **http://localhost:5173**.

> If port 5173 is busy, run `npm run dev -- --port 5180` and add that origin to
> `CORS_ORIGINS` on the backend, or the browser will block every request.

### 3. Log in

| Field | Value |
|---|---|
| Email | `T6-LEAD@synapse.example` |
| Password | `ChangeMe123!` |

That is the **admin** account. Other seeded roles are below — all share the same
password.

| Email | Role | Can do |
|---|---|---|
| `T6-LEAD@synapse.example` | `admin` | everything |
| `T6-BE1@synapse.example` | `workflow_builder` | ingest, query |
| `T6-DEV1@synapse.example` | `reviewer` | query, review queue |
| `T6-DATA1@synapse.example` | `analyst` | ingest, query, analytics |
| `T6-DATA2@synapse.example` | `analyst` | ingest, query, analytics |
| `T6-DATA3@synapse.example` | `api_consumer` | query only |

> **The domain is `.example`, not `.local`.** `.local` is an RFC 6762
> special-use TLD that the email validator always rejects, so a `@synapse.local`
> address can never log in.

> **These accounts are seeded only when `ENVIRONMENT=local`** (the default).
> The password is published in this repo, so any other environment skips
> seeding — and setting `SEED_DEMO_USERS=true` outside local is refused at
> startup rather than silently obeyed.

---

## Using the application

The UI has five pages. Here is the full loop, in the order you would actually
use it.

### Upload — get documents into the system

Two modes:

- **Paste text** — give it a title and paste the body.
- **Upload file** — drop a `.txt`, `.md`, `.pdf` or `.docx`. Title defaults to
  the filename.

| Format | How it is read |
|---|---|
| `.txt`, `.md` | read directly |
| `.pdf` | text layer via `pypdf` |
| `.docx` | paragraphs **and table cells** via `python-docx`, with a stdlib zip/XML fallback |

On submit the document is parsed, classified, chunked, embedded and indexed in
one pass. The page then lists every ingested document with its category,
confidence and chunk count, and a **Category** filter across the taxonomy.

Each document shows one of these classification states:

| Badge | Meaning |
|---|---|
| `auto` + a percentage | classified confidently, no human needed |
| `pending review` | confidence below threshold — sitting in the review queue |
| `confirmed` | a human approved the label |
| `corrected` | a human replaced the label |
| `rejected` | a human rejected it; the label is cleared |

**Re-classify** re-runs classification on a single document — useful after the
taxonomy version changes.

> **Scanned PDFs do not work yet.** A PDF with no text layer is image-only and
> needs OCR, which is not implemented. Rather than silently ingesting an empty
> document, the upload fails with a message pointing at the unimplemented OCR
> path.

### Chat — ask grounded questions

Type a question about your ingested documents. You get back:

- **The answer**, built only from retrieved chunks.
- **Numbered citations** `[1]`, `[2]` — each with a similarity score and the
  snippet used.
- **A confidence score.**
- **A refusal**, if nothing retrieved was relevant enough. This is correct
  behaviour, not a bug — it means the honest answer is "your documents do not
  cover this."

If the answer's confidence falls below `REVIEW_CONFIDENCE_THRESHOLD`, it is
still returned to you *and* copied into the review queue.

### Review Queue — the human-in-the-loop gate

Shows everything the system was not confident about. Two kinds of item:

| Type | What you are judging |
|---|---|
| `answer` | a low-confidence RAG answer |
| `classification` | a low-confidence document label |

Three decisions, and **a rationale is mandatory for all of them** (a decision
with no reason is not auditable):

- **Approve** — the proposal was right.
- **Edit** — supply the correct answer, or the correct taxonomy label.
- **Reject** — the proposal was wrong and has no replacement.

For a classification item the decision is **written back onto the document**:
approve → `confirmed`, edit → `corrected` with your label, reject → label
cleared. Two guards apply: an edited label must be a real taxonomy label, and an
item whose proposed label was unusable cannot simply be approved — you must
supply one or reject it.

Every decision also writes a `Feedback` row, which is the intended seed corpus
for a future evaluation dataset.

### Usage — cost and volume

Aggregates every logged provider call, by day and by user: call count, tokens,
cost in USD, and average latency. Operations are tracked separately
(`embedding`, `completion`, `classification`), so the cost of auto-classifying
an ingest is visible apart from the cost of answering questions.

With the default mock provider every cost is `$0.00` — the plumbing is real, the
price is zero.

### Login / Log out

JWT-based, stored in `localStorage`. The navigation bar shows your role id and
role. Pages you lack permission for return `403` from the API.

---

## Using the API

Base path `/api/v1`. Full reference: **[docs/API.md](docs/API.md)**. Interactive
Swagger UI at `/docs` while the backend runs.

Authenticate with **either** a JWT or an API key:

```
Authorization: Bearer <jwt>      # from POST /auth/login
X-API-Key: <key>                 # from POST /auth/api-keys, admin-issued
```

### Endpoints at a glance

| Method | Path | Roles | Purpose |
|---|---|---|---|
| `POST` | `/auth/login` | public | exchange credentials for a JWT |
| `POST` | `/auth/api-keys` | admin | issue a scoped key (**shown once**) |
| `GET` | `/auth/api-keys` | admin | list issued keys |
| `POST` | `/documents` | admin, workflow_builder, analyst | multipart upload |
| `POST` | `/documents/text` | admin, workflow_builder, analyst | JSON text ingest |
| `GET` | `/documents?label=` | any | list, optionally filtered by category |
| `GET` | `/documents/taxonomy` | any | the active label set |
| `POST` | `/documents/{id}/reclassify` | admin, workflow_builder | re-run classification |
| `POST` | `/query` | any | grounded question answering |
| `GET` | `/review/queue` | admin, reviewer | pending review items |
| `POST` | `/review/queue/{id}/decision` | admin, reviewer | approve / edit / reject |
| `GET` | `/analytics/usage` | admin, analyst | cost and volume aggregates |
| `GET` | `/health` | public | liveness + active backends + index state |

### A complete session

```bash
API=http://localhost:8000/api/v1

# 1. Log in
TOKEN=$(curl -s -X POST $API/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"T6-LEAD@synapse.example","password":"ChangeMe123!"}' \
  | jq -r .access_token)

# 2. Ingest a document
curl -s -X POST $API/documents/text \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"Refund Policy","text":"Customers may request a full refund within 30 days of purchase. Refunds reach the original payment method within 5 business days."}' | jq

# 3. Or upload a file
curl -s -X POST $API/documents \
  -H "Authorization: Bearer $TOKEN" -F 'file=@contract.pdf' | jq

# 4. Ask a grounded question
curl -s -X POST $API/query \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"How long do I have to request a refund?"}' | jq

# 5. See what needs human review
curl -s "$API/review/queue?status=pending" -H "Authorization: Bearer $TOKEN" | jq

# 6. Decide on an item (rationale is required)
curl -s -X POST $API/review/queue/<ITEM_ID>/decision \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"decision":"approved","rationale":"Matches the source document."}' | jq

# 7. Check cost
curl -s $API/analytics/usage -H "Authorization: Bearer $TOKEN" | jq
```

### Programmatic access with an API key

```bash
# Admin issues a scoped key - the plaintext is returned exactly once
KEY=$(curl -s -X POST $API/auth/api-keys \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"reporting-bot","role":"api_consumer"}' | jq -r .api_key)

curl -s -X POST $API/query -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"question":"refund window?"}' | jq
```

Only a HMAC-SHA256 hash of the key is ever stored, so a stolen database dump
cannot be used to forge working keys.

### Health

```bash
curl -s http://localhost:8000/health | jq
```

```json
{
  "status": "ok",
  "environment": "local",
  "llm_provider": "mock",
  "vector_store_backend": "pgvector",
  "stored_chunks": 42,
  "indexed_chunks": 42,
  "retrieval_ready": true
}
```

`stored_chunks` (database) and `indexed_chunks` (vector store) should match.
**`retrieval_ready: false` means they have diverged** — the documents are still
listed in the UI but no query can retrieve them. See
[Troubleshooting](#troubleshooting).

---

## Roles and permissions

Five fixed roles, enforced by `require_role()` on every endpoint.

| Role | Ingest | Query | Review queue | Analytics | Issue API keys |
|---|:--:|:--:|:--:|:--:|:--:|
| `admin` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `workflow_builder` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `reviewer` | ❌ | ✅ | ✅ | ❌ | ❌ |
| `analyst` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `api_consumer` | ❌ | ✅ | ❌ | ❌ | ❌ |

Roles attach to **users and API keys alike**, so a key can be scoped more
narrowly than the admin who issued it. Full roster in
[docs/TEAM.md](docs/TEAM.md).

---

## Configuration

Copy `.env.example` to `.env` and edit. Every value has a working default —
you do not need to set anything to run locally.

### General

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `local` | Anything other than `local` enables the deployment safety checks |
| `DEBUG` | `false` | Informational only |
| `SECRET_KEY` | placeholder | **Signs JWTs and HMACs API-key hashes.** Startup fails with the placeholder unless `ENVIRONMENT=local` |
| `SEED_DEMO_USERS` | unset | Unset → seeds only when local. `true` outside local is refused |
| `CORS_ORIGINS` | localhost:5173, :3000 | Comma-separated or a JSON array |
| `DATABASE_URL` | `sqlite:///./synapse_local.db` | Any SQLAlchemy URL; Postgres for real use |

Generate a real secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Retrieval behaviour

| Variable | Default | Notes |
|---|---|---|
| `CHUNK_SIZE_TOKENS` | `200` | Token window per chunk |
| `CHUNK_OVERLAP_TOKENS` | `40` | Overlap, so facts are not split across a boundary |
| `RETRIEVAL_TOP_K` | `4` | Chunks retrieved per question |
| `SIMILARITY_THRESHOLD` | `0.15` | Below this, a chunk is not trustworthy evidence. Nothing clears it → refusal |
| `REVIEW_CONFIDENCE_THRESHOLD` | `0.55` | Below this, the answer also goes to the review queue |

### Classification

| Variable | Default | Notes |
|---|---|---|
| `CLASSIFICATION_ENABLED` | `true` | Set `false` to skip a provider call per ingest |
| `CLASSIFICATION_SAMPLE_CHARS` | `4000` | Only the first N characters are classified — category signal sits at the top of a document, and this bounds cost |
| `CLASSIFICATION_REVIEW_THRESHOLD` | `0.55` | Below this, the label is provisional and queued for a human |

### Providers

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` or `litellm` |
| `VECTOR_STORE_BACKEND` | `inmemory` | `inmemory`, `chroma` or `pgvector` |
| `EMBEDDING_DIM` | `256` | Must match the model — mock is 256, `text-embedding-3-small` is 1536 |

---

## Running with Docker Compose

Brings up Postgres, the backend and the frontend together:

```bash
cp .env.example .env
docker compose up --build
```

- Frontend → http://localhost:5173
- Backend → http://localhost:8000
- Postgres → localhost:5432

To point the frontend at a different API, pass it as a **build** argument —
Vite inlines `VITE_*` into the bundle at build time, so a runtime environment
variable has no effect:

```bash
docker compose build --build-arg VITE_API_BASE_URL=https://api.example.com/api/v1
```

ChromaDB and LiteLLM are not separate services here. They are in-process,
pluggable concerns, not infrastructure.

---

## Using a real LLM provider

Install the optional backends, then flip two environment variables:

```bash
pip install -r requirements.txt -r requirements-optional.txt
```

```env
LLM_PROVIDER=litellm
LITELLM_MODEL=gpt-4o-mini                      # any litellm-supported model id
LITELLM_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536                             # must match the embedding model
OPENAI_API_KEY=sk-...                          # or ANTHROPIC_API_KEY, etc.
LITELLM_FALLBACK_MODELS=gpt-4o-mini,claude-3-5-haiku-20241022
```

No code changes — `get_llm_provider()` selects the implementation from
`LLM_PROVIDER` alone. Real per-call costs then flow into the usage dashboard
automatically.

> **Changing `EMBEDDING_DIM` invalidates existing embeddings.** Different models
> produce vectors of different dimensionality and different geometry, so
> documents indexed under the old model must be re-ingested.

`requirements-optional.txt` is separate on purpose: neither package is needed
for the default path, and keeping them out means an upstream release being
withdrawn from PyPI cannot break the core install.

---

## Choosing a vector store

| Backend | Survives restart? | Needs | Use for |
|---|:--:|---|---|
| `inmemory` | ❌ | nothing | local dev, tests |
| `chroma` | ✅ | `chromadb` + a persistent directory | single-host deployments with a disk |
| `pgvector` | ✅ | PostgreSQL with the `vector` extension | **anything deployed** |

**`inmemory` loses every embedding when the process restarts.** The documents
and chunks stay in the database, so the UI keeps listing them as ingested while
every query refuses — a silent failure, not a loud one. That is fine locally and
wrong anywhere that restarts.

`pgvector` keeps the embeddings in the same Postgres that holds the documents,
so the two cannot drift apart:

```env
DATABASE_URL=postgresql+psycopg2://user:pass@host/db?sslmode=require
VECTOR_STORE_BACKEND=pgvector
EMBEDDING_DIM=256
```

It needs no extra Python package — only the server-side extension, which Neon,
Supabase and RDS all ship. The extension, table and HNSW index are created on
first use.

---

## Deployment

Full runbook: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — Cloudflare Pages +
Render + Neon, entirely on free tiers. `render.yaml` in the repo root is a
Render Blueprint for the backend.

Four things to get right:

1. **`SECRET_KEY` must be a real secret.** The app refuses to start with the
   placeholder once `ENVIRONMENT != local`. Let your host generate it.
2. **`VITE_API_BASE_URL` is build-time.** Setting it on a running container does
   nothing — it must be a build argument.
3. **`CORS_ORIGINS` must list the frontend origin exactly.** Otherwise every
   browser request fails preflight while `curl` keeps working.
4. **Use `VECTOR_STORE_BACKEND=pgvector`.** Free hosts restart constantly.

The backend honours `$PORT` (defaulting to 8000), which is how Render, Fly,
Cloud Run and Hugging Face Spaces assign a listen port.

Run migrations before first use:

```bash
cd backend
DATABASE_URL="<your postgres url>" alembic upgrade head
```

---

## Testing

```bash
cd backend
pytest                      # 116 passed, 13 skipped
ruff check app tests
```

The 13 skips are the pgvector suite, which needs a real Postgres:

```bash
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg16
TEST_DATABASE_URL=postgresql+psycopg2://postgres:pw@localhost:5432/postgres pytest
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

The whole backend suite runs with **zero external dependencies** — no network,
no Postgres, no API keys — because the mock provider and in-memory store make
the full pipeline exercisable offline. PDF and DOCX fixtures are built
in-process (a real PDF byte stream with a proper xref table, a real `.docx` zip
package), so no binaries are checked in.

CI runs six jobs: backend lint + tests, frontend lint + build, container builds,
an **actual uvicorn boot with a `/health` probe** (a passing test suite is not
evidence the app starts), an alembic upgrade/downgrade round-trip, and the
pgvector suite against a real Postgres service container.

---

## What is built and what is not

### Working

- **Auth & RBAC** — JWT login, scoped API keys, role gates on every endpoint.
- **Ingestion** — multipart and JSON, `.txt` / `.md` / `.pdf` / `.docx`, real
  token-window chunking with overlap, real embeddings, real vector indexing.
- **Classification** — every document labelled from a versioned taxonomy via a
  constrained-label prompt over the *same* provider seam RAG uses. Never fails
  an ingest: an off-taxonomy label, an unparseable response or a provider outage
  all degrade to unclassified and route to a human.
- **Grounded RAG** — cosine retrieval, numbered citations, transparent
  confidence, and a real refusal path that skips the LLM entirely.
- **Human review** — one queue for answers and labels, mandatory rationales,
  classification decisions written back onto the document.
- **Usage & cost tracking** — tokens, cost and latency per call, aggregated by
  day and by user.
- **Frontend** — five real React + TypeScript + Tailwind pages wired to the live
  API.

### Scaffolded — documented, no logic

All under `backend/app/scaffold/`, each with its spec reference:

| Feature | Where | Note |
|---|---|---|
| OCR for scanned PDFs | `scaffold/parsers.py` | `parse_pdf` already reports which pages have no text layer — that list is the intended trigger |
| Email ingestion (`.eml` / `.msg`) | `scaffold/parsers.py` | should recurse into `parse_upload` for attachments |
| No-code workflow DAG builder | `scaffold/workflow_builder.py` | needs a `workflows` table, not yet modelled |
| Structured field extraction | `scaffold/field_extraction.py` | would key schemas off the existing taxonomy |
| promptfoo CI evaluation gate | `scaffold/promptfoo/` | config present, fixtures empty, not wired into CI |

Each is a registration away from working: parsers register in a `PARSERS` table,
providers implement one ABC. None require changes to existing call sites.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every query refuses, but documents are listed | `/health` shows `retrieval_ready: false`. The vector store lost its contents — you are on `inmemory` and the process restarted. Switch to `pgvector` and re-ingest. |
| Backend exits at startup mentioning `SECRET_KEY` | The placeholder is set with `ENVIRONMENT != local`. Generate a real one. |
| Login fails for a seeded account | Use `@synapse.example`, not `@synapse.local`. And seeding only happens when `ENVIRONMENT=local`. |
| Browser requests all fail; `curl` works | The frontend origin is not in `CORS_ORIGINS`. Scheme and host must match exactly, no trailing slash. |
| Frontend calls `localhost:8000` in production | `VITE_API_BASE_URL` was not set **at build time**. Rebuild with the build argument. |
| `404` with `%20` in the path | Trailing space in `VITE_API_BASE_URL`. |
| PDF upload returns `503` | `pypdf` is not installed — `pip install -r requirements.txt`. |
| PDF upload returns `400` about OCR | The PDF is image-only with no text layer. OCR is not implemented. |
| First request after idle times out, then works | Serverless Postgres (Neon) scales to zero and a free Render service sleeps after 15 min. The first request wakes them and can take 30-60s. Retry once before investigating. |
| Answers look shallow with the mock provider | Expected. The mock embedder is a bag-of-words hashing trick for offline determinism, not a semantic model. Switch to `litellm` for real quality. |

---

## Repository layout

```
backend/app/
  core/        config (+ startup safety checks), security (JWT/API keys/roles), RBAC deps
  db/          base_class (Base only) + base (model registry) + session/seed
  models/      User, ApiKey, Document, Chunk, QueryLog, ReviewItem, Feedback, UsageLog
  schemas/     Pydantic request/response models
  api/v1/      auth, documents, query, review, analytics routers
  services/    chunking, parsers, classification, llm_provider, vector_store, rag, ingestion
  scaffold/    documented, unimplemented extension points
backend/alembic/                   migration environment + schema migrations
backend/tests/                     pytest suite
backend/requirements.txt           core dependencies
backend/requirements-optional.txt  chromadb + litellm (opt-in backends)
frontend/src/                      React + TS + Tailwind SPA
frontend/nginx.conf                SPA history-mode fallback for the container
docs/                              architecture, API, team/RBAC, responsible AI, deployment
render.yaml                        Render Blueprint for the backend
.github/workflows/ci.yml           CI: lint, tests, boot check, migrations, pgvector, images
```

## Documentation

| Document | Contents |
|---|---|
| [docs/API.md](docs/API.md) | Full endpoint reference with request/response shapes |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and the pluggable seams |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Free-tier deployment runbook |
| [docs/RESPONSIBLE_AI.md](docs/RESPONSIBLE_AI.md) | Grounding, citation, refusal and review policy |
| [docs/TEAM.md](docs/TEAM.md) | Role roster and the RBAC matrix |
