# Project Synapse - Responsible AI Policy

This document reflects the grounding / citation / refusal / human-in-the-loop
policy specified in the FRD ("Responsible AI & Governance") and describes
exactly how it is enforced in code today.

## 1. Grounding

Every answer returned by `POST /api/v1/query` must be derived only from
retrieved document chunks, never from the LLM's parametric knowledge. This
is enforced structurally, not just by prompt instruction:

- `app/services/rag.py::_build_grounded_prompt()` builds a prompt whose
  only source material is the numbered `CONTEXT` block of retrieved
  chunks; the model is instructed to answer only from that context.
- The default `MockProvider` (`app/services/llm_provider.py`) goes
  further and is *structurally* incapable of ungrounded generation: its
  "answer" is extracted verbatim from the supplied context, so grounding
  failures in the mock path are a code bug, not a probabilistic risk. Its
  classification replies are constrained the same way - it can only return
  a label listed in the prompt, or `unknown`.
- When a real provider (`LiteLLMProvider`) is enabled, grounding relies on
  prompt instructions plus the citation/refusal checks below as a
  backstop - this is the seam where `backend/app/scaffold/promptfoo/`
  is intended to provide a CI-gated regression check on groundedness.

## 2. Citation

Every claim in a grounded answer is tied back to a specific source chunk
via a `[n]` marker, and every `QueryResponse.citations[]` entry carries
`document_id`, `chunk_id`, similarity `score`, and a text `snippet` - so a
reviewer or end user can verify any answer against its source without
leaving the response payload. See `backend/tests/test_rag.py::test_grounded_answer_cites_the_ingested_document`
for the enforced contract.

## 3. Refusal Over Hallucination

If no retrieved chunk's similarity score clears `SIMILARITY_THRESHOLD`
(default `0.15`, see `backend/app/core/config.py`), the platform returns a
documented refusal (`INSUFFICIENT_CONTEXT_MESSAGE` in `app/services/rag.py`)
instead of calling the LLM at all. This is a hard gate, not a suggestion to
the model - see `backend/tests/test_rag.py::test_insufficient_context_triggers_documented_refusal`.

## 4. Human-in-the-Loop Review

Confidence is computed transparently from retrieval strength (top score +
agreement across retrieved chunks - see `_compute_confidence()`), not a
black-box model self-report. Any answer below `REVIEW_CONFIDENCE_THRESHOLD`
(default `0.55`) is written to the `review_items` table (`status=pending`)
for a human with the `reviewer` or `admin` role to approve, edit, or reject
via `POST /api/v1/review/queue/{id}/decision`, with a mandatory rationale.

Refusals are *not* routed to review - a documented, correct refusal is
already a safe outcome and does not need human adjudication; only
low-confidence *answers* do.

### Classification review (FRD 7)

Document classifications are governed on the same terms and share the same
queue (`review_items.item_type` distinguishes them), so reviewers work in
one place and every decision lands in the same `feedback` table:

- A label below `CLASSIFICATION_REVIEW_THRESHOLD` (default `0.55`), or one
  the classifier could not produce at all, is **provisional**: the document
  is stored with `classification_status=pending_review` and, when the label
  is unusable, no label at all. A sentinel string such as `"unknown"` is
  never written, because downstream routing asks "is this classified?" and
  a sentinel would answer yes.
- A resolved classification is written back onto the document, so what
  downstream consumers read is the *confirmed* or *corrected* label plus the
  fact that a human stands behind it (`confirmed` / `corrected`), not a
  model guess.
- A **rejected** label is cleared rather than left in place: a category a
  human has explicitly called wrong must not keep driving routing.
- A reviewer cannot invent a category. An `edited` decision must name a real
  taxonomy label, and an item whose proposed label is unusable cannot be
  approved at all - there is nothing to approve.
- Classification confidence is the model's own stated confidence, parsed
  from its response, not a number we infer on its behalf. Under the default
  `MockProvider` it is a transparent lexical-evidence score (share of total
  evidence + margin over the runner-up), so the routing decision is
  inspectable rather than a black box.

## 5. Feedback Loop

Every reviewer decision is persisted to the `feedback` table
(`app/models/feedback.py`) with the decision and rationale. This is the
intended input to the promptfoo regression corpus
(`backend/app/scaffold/promptfoo/promptfooconfig.yaml`, scaffolded, not
yet wired into CI) so that real reviewer judgments - not synthetic
examples - drive the eval gate over time.

## 6. Usage & Cost Transparency

Every provider call is logged (`usage_logs` table) with provider, model,
token counts, cost, and latency, surfaced via
`GET /api/v1/analytics/usage`. That includes the classification call made
at ingest time (`operation=classification`), so enabling auto-classification
cannot quietly add unattributed spend. This applies identically to the mock
provider (always `$0.00`, real token counts) and any real provider, so
switching providers never silently loses cost visibility.
