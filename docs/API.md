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
char_count, chunk_count, created_at`), where `source_type` is `text`, `pdf`,
or `docx`.

Errors:

| Status | Cause |
|---|---|
| `400` | empty body, missing `title` for text, or a corrupt/unreadable file |
| `415` | unsupported extension (e.g. `.zip`, legacy `.doc`) |
| `503` | format is supported but its optional package is not installed (`pypdf`) |

A PDF whose pages are all image-only extracts to empty text and returns
`400` pointing at the unimplemented OCR path, rather than silently
ingesting a zero-chunk document.

### `POST /documents/text` (roles: admin, workflow_builder, analyst)
JSON convenience alias: `{ "title": string, "text": string }`.

### `GET /documents` (any authenticated role)
Lists all ingested documents with chunk counts.

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

### `GET /review/queue?status=pending` (roles: admin, reviewer)
Lists `ReviewItem` rows, optionally filtered by status
(`pending|approved|edited|rejected`).

### `POST /review/queue/{review_item_id}/decision` (roles: admin, reviewer)
Body: `{ "decision": "approved"|"edited"|"rejected", "rationale": string, "final_answer"?: string }`
Rationale is required for every decision. Also writes a `Feedback` row for
future eval-dataset building.

## Analytics

### `GET /analytics/usage` (roles: admin, analyst)
Returns per-day and per-user aggregates (`total_calls, total_tokens,
total_cost_usd, avg_latency_ms`) computed from every logged provider call
(embedding + completion).

## Health

### `GET /health`
No auth required. Returns app name, environment, and the currently active
`llm_provider` / `vector_store_backend`.
