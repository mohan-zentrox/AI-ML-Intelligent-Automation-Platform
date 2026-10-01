# Project Synapse - API Reference (v1)

Base path: `/api/v1`. Interactive docs available at `/docs` (Swagger UI)
and `/redoc` when the backend is running.

Auth: send either
- `Authorization: Bearer <jwt>` (from `POST /auth/login`), or
- `X-API-Key: <key>` (from `POST /auth/api-keys`, admin-issued)

## Auth

### `POST /auth/login`
Body: `{ "email": string, "password": string }`
Returns: `{ access_token, token_type, role, role_id }`

### `POST /auth/api-keys` (role: admin)
Body: `{ "name": string, "role": "admin"|"workflow_builder"|"reviewer"|"analyst"|"api_consumer" }`
Returns: `{ id, name, role, key_prefix, api_key }` - `api_key` is shown once only.

### `GET /auth/api-keys` (role: admin)
Lists the caller's own issued keys (hash never returned).

## Documents

### `POST /documents` (roles: admin, workflow_builder, analyst)
Multipart form: `title` + `text`, OR `file`.

Supported upload formats (registry: `app.services.parsers.PARSERS`):

| Extension | Parser | Notes |
|---|---|---|
| `.txt`, `.md` | stdlib | `source_type` is recorded as `text` |
| `.pdf` | `pypdf` | text layer only; scanned/image-only pages need OCR (FRD 4.2.2, not implemented) |
| `.docx` | `python-docx`, with a stdlib zip/XML fallback | paragraphs + table cells |

`title` is optional for file uploads (defaults to the filename) and required
for the `text` form field. Returns `DocumentOut` (`id, title, source_type,
char_count, chunk_count, created_at`, plus the classification fields below),
where `source_type` is `text`, `pdf`, or `docx`.

Errors:

| Status | Cause |
|---|---|
| `400` | empty body, missing `title` for text, or a corrupt/unreadable file |
| `413` | file is larger than `MAX_UPLOAD_BYTES` (default 10 MB) |
| `415` | unsupported extension (e.g. `.zip`, legacy `.doc`) |
| `503` | format is supported but its optional package is not installed (`pypdf`) |

A PDF whose pages are all image-only extracts to empty text and returns
`400` pointing at the unimplemented OCR path, rather than silently
ingesting a zero-chunk document.

### `POST /documents/text` (roles: admin, workflow_builder, analyst)
JSON convenience alias: `{ "title": string, "text": string }`.

### `GET /documents?label=<label>` (any authenticated role)
Lists all ingested documents with chunk counts, newest first. `label`
filters by classification; an unknown label returns `400` rather than an
empty list.

## Classification (FRD 7)

Every ingested document is classified into a versioned taxonomy at ingest
time (unless `CLASSIFICATION_ENABLED=false`). `DocumentOut` carries:

| Field | Meaning |
|---|---|
| `classification_label` | the assigned category, or `null` if unclassified/unclassifiable/rejected |
| `classification_confidence` | model confidence in `[0,1]`; `null` once a human has supplied the label |
| `classification_status` | `unclassified`, `auto`, `pending_review`, `confirmed`, `corrected`, or `rejected` |
| `taxonomy_version` | the taxonomy the label was produced under |
| `classified_at` | when the classifier last ran |

A classification at or above `CLASSIFICATION_REVIEW_THRESHOLD` is stored
with status `auto`. Below it - or when the classifier returns no usable
label - the label is provisional (`pending_review`) and a classification
`ReviewItem` is opened. An unusable label is stored as `null`, never as the
string `"unknown"`, so downstream routing cannot mistake it for a category.

### `GET /documents/taxonomy` (any authenticated role)
Returns `{ version, categories: [{ label, description }] }` - the active
label set, so clients render pickers without hardcoding it.

### `POST /documents/{document_id}/reclassify` (roles: admin, workflow_builder)
Re-runs classification for one document and returns the updated
`DocumentOut`. Used for documents ingested under a superseded
`taxonomy_version` or whose label was rejected. Any earlier *pending*
classification review for that document is withdrawn, so one document never
has two competing proposals in the queue. `404` if the document does not
exist, `400` if it has no text.

## Query (Grounded RAG)

### `POST /query` (any authenticated role)
Body: `{ "question": string }`
Returns:
```json
{
  "answer": "string",
  "citations": [{"marker": 1, "document_id": "...", "chunk_id": "...", "score": 0.83, "snippet": "..."}],
  "confidence": 0.74,
  "refused": false,
  "query_log_id": "...",
  "routed_to_review": false
}
```
If no retrieved chunk clears `SIMILARITY_THRESHOLD`, `refused=true`,
`citations=[]`, `confidence=0.0`, and `answer` is the documented
insufficient-context message - the LLM is never called in that case.

## Review Queue

One queue carries two kinds of item, distinguished by `item_type`:

| `item_type` | Source | `proposed_answer` holds | `document_id` |
|---|---|---|---|
| `answer` | low-confidence RAG answer | the generated answer text | `null` |
| `classification` | low-confidence document label | the proposed taxonomy label | the document |

### `GET /review/queue?status=pending&item_type=classification` (roles: admin, reviewer)
Lists `ReviewItem` rows, optionally filtered by status
(`pending|approved|edited|rejected`) and by `item_type`
(`answer|classification`). An unknown `item_type` returns `400`.

### `POST /review/queue/{review_item_id}/decision` (roles: admin, reviewer)
Body: `{ "decision": "approved"|"edited"|"rejected", "rationale": string, "final_answer"?: string }`
Rationale is required for every decision. Also writes a `Feedback` row for
future eval-dataset building.

For a `classification` item the decision is written back onto the document:

| Decision | Effect on the document |
|---|---|
| `approved` | label kept, status becomes `confirmed` |
| `edited` | label replaced by `final_answer`, status becomes `corrected`, model confidence cleared |
| `rejected` | label cleared to `null`, status becomes `rejected` |

Two extra validations apply to classification items, both `400`:
`final_answer` on an `edited` decision must be a real taxonomy label, and an
item whose proposed label is unusable (`unknown`) cannot be `approved` -
the reviewer has to supply a label or reject it.

## Analytics

### `GET /analytics/usage` (roles: admin, analyst)
Returns per-day and per-user aggregates (`total_calls, total_tokens,
total_cost_usd, avg_latency_ms`) computed from every logged provider call.
Each row's `operation` is `embedding`, `completion`, or `classification`, so
the cost of auto-classifying an ingest is visible separately from RAG.

## Health

### `GET /health`
No auth required. Returns app name, environment, the active `llm_provider` /
`vector_store_backend`, and the two chunk counts:

```json
{
  "status": "ok",
  "app": "Project Synapse",
  "environment": "local",
  "llm_provider": "mock",
  "vector_store_backend": "pgvector",
  "stored_chunks": 42,
  "indexed_chunks": 42,
  "retrieval_ready": true
}
```

`stored_chunks` (relational) and `indexed_chunks` (vector store) should track
each other. `stored_chunks > 0` with `indexed_chunks == 0` means the vector
store lost its contents - typically `VECTOR_STORE_BACKEND=inmemory` after a
restart - and every query will refuse until those documents are re-ingested.
`retrieval_ready` is false in exactly that case.

The counts are omitted (rather than the endpoint failing) if the database or
vector store cannot be reached: a probe that 500s on a failed diagnostic is
worse than one missing an optional field.
