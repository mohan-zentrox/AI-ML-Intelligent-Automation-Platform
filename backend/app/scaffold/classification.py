"""
SCAFFOLD ONLY - Document classification.

Reference: FRD section 7 "Automated Document Classification". Intended to
tag an ingested Document with a category (e.g. invoice, contract, policy,
support-ticket) immediately after ingestion, driving downstream routing
(e.g. which extraction schema to apply - see field_extraction.py).

Not wired into app.services.ingestion.ingest_document yet.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    taxonomy_version: str


def classify_document(document_text: str) -> ClassificationResult:
    """TODO(FRD 7.1): classify `document_text` into the platform's document
    taxonomy.

    Suggested approach: start with an LLMProvider.complete() call using a
    constrained-label prompt (reuse app.services.llm_provider.get_llm_provider
    so this inherits the same mock/litellm swappability as RAG), then
    graduate to a fine-tuned/lightweight classifier if volume warrants it.
    Low-confidence classifications should route through the same
    ReviewItem/human-in-the-loop mechanism used for RAG answers
    (see app/models/review_item.py) rather than a separate queue.
    """
    raise NotImplementedError("Document classification is scaffolded - see FRD 7.1")
