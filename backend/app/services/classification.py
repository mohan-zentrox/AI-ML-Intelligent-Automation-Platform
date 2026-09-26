"""
Automated document classification.

Reference: FRD section 7 "Automated Document Classification". Every ingested
document is tagged with exactly one category from a versioned taxonomy, which
is what downstream routing keys off (e.g. which extraction schema to apply -
see app/scaffold/field_extraction.py).

Design notes:

  * The classifier is a *constrained-label* prompt over the same
    `LLMProvider` seam RAG uses (app/services/llm_provider.py), so it
    inherits mock/litellm swappability for free and never talks to a vendor
    SDK directly. No second model stack, no second set of credentials.

  * The taxonomy lives here as a single `TAXONOMY` registry keyed by label
    (same shape as the `PARSERS` registry in parsers.py): adding a category
    is one entry, no call-site changes. `TAXONOMY_VERSION` is stamped onto
    every stored classification so a taxonomy change is detectable after the
    fact rather than silently rewriting history - documents classified under
    an older version can be found and re-run via
    `POST /api/v1/documents/{id}/reclassify`.

  * The model is asked for a label *and* a confidence, both parsed out of a
    two-line response. Anything unparseable, or any label outside the
    taxonomy, degrades to `UNKNOWN_LABEL` at confidence 0.0 rather than
    raising - an unclassifiable document must still ingest successfully, it
    just arrives in the human review queue. Same principle as the RAG
    refusal path: never guess, escalate instead (docs/RESPONSIBLE_AI.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.llm_provider import CompletionResult, LLMProvider, get_llm_provider

settings = get_settings()

# Bump when labels are added/removed/redefined. Stored on every Document row
# so stale classifications are identifiable (see module docstring).
TAXONOMY_VERSION = "v1"

# Not a taxonomy member: the reserved result for "the classifier did not
# return a usable label". Always routes to human review.
UNKNOWN_LABEL = "unknown"


@dataclass(frozen=True)
class Category:
    """One taxonomy entry.

    `description` is doing double duty on purpose: it is the definition the
    real LLM reads to pick a label, and it is the lexical evidence the
    offline MockProvider scores against (see
    `MockProvider._template_classification`). Keep descriptions
    discriminative - concrete terms that actually appear in that kind of
    document - rather than abstract.
    """

    label: str
    description: str


TAXONOMY: dict[str, Category] = {
    c.label: c
    for c in (
        Category(
            "invoice",
            "Billing document requesting payment: invoice number, bill to, "
            "line items, quantity, unit price, subtotal, sales tax, total "
            "amount due, payment terms, remittance, purchase order.",
        ),
        Category(
            "contract",
            "Binding agreement between parties: this agreement, effective "
            "date, counterparty, term and termination, obligations, "
            "warranties, liability, indemnification, confidentiality, "
            "governing law, executed signature.",
        ),
        Category(
            "policy",
            "Internal rules and procedures staff must follow: policy, scope, "
            "applies to all employees, guidelines, standards, compliance, "
            "mandatory, prohibited, exceptions, approval, revision history.",
        ),
        Category(
            "report",
            "Analytical or status write-up of findings: executive summary, "
            "methodology, findings, results, analysis, metrics, quarter, "
            "revenue, growth, trend, recommendations, conclusion, appendix.",
        ),
        Category(
            "support_ticket",
            "Customer or internal support request: ticket, issue, reported "
            "by, steps to reproduce, expected behaviour, error message, "
            "stack trace, priority, severity, assigned, resolution, "
            "workaround.",
        ),
        Category(
            "correspondence",
            "Letter, memo or email thread between people: dear, regards, "
            "sincerely, subject, sender, recipient, forwarded message, "
            "reply, attached, following up, best wishes.",
        ),
        Category(
            "other",
            "General reference material matching none of the more specific "
            "categories: miscellaneous notes, background, overview, "
            "reference, general information.",
        ),
    )
}


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    taxonomy_version: str
    # How the label was produced: the provider name ("mock"/"litellm"), or
    # "skipped"/"failed" when no usable provider call happened.
    method: str = "llm"
    # The underlying completion, so the caller can log tokens/cost/latency to
    # the usage ledger exactly like rag.py does. None when no call was made.
    usage: CompletionResult | None = None
    error: str | None = None

    @property
    def needs_review(self) -> bool:
        """True when the label must not be trusted for downstream routing
        without a human confirming it first."""
        return (
            self.label == UNKNOWN_LABEL
            or self.confidence < settings.CLASSIFICATION_REVIEW_THRESHOLD
        )


def build_classification_prompt(document_text: str) -> str:
    """Constrained-label prompt: candidates inline, verbatim-copy
    instruction, fixed two-line response format.

    The `[label] description` candidate format and the `LABEL:`/`CONFIDENCE:`
    response contract are also what MockProvider keys off to answer this
    offline - keep the two in sync if you change the shape here.
    """
    label_block = "\n".join(f"[{c.label}] {c.description}" for c in TAXONOMY.values())
    sample = document_text.strip()[: settings.CLASSIFICATION_SAMPLE_CHARS]
    return (
        "You are Project Synapse's document classifier.\n"
        "Assign the DOCUMENT below exactly one label from CANDIDATE LABELS. "
        "Never invent a label that is not listed.\n\n"
        f"CANDIDATE LABELS:\n{label_block}\n\n"
        f"DOCUMENT:\n{sample}\n\n"
        "INSTRUCTIONS:\nRespond with exactly two lines and nothing else:\n"
        "LABEL: <one label copied verbatim from CANDIDATE LABELS>\n"
        "CONFIDENCE: <a decimal between 0.0 and 1.0>"
    )


_LABEL_RE = re.compile(r"^\s*LABEL:\s*\[?([A-Za-z0-9 _-]+?)\]?\s*$", re.MULTILINE)
_CONFIDENCE_RE = re.compile(r"^\s*CONFIDENCE:\s*([0-9]*\.?[0-9]+)\s*$", re.MULTILINE)


def parse_classification_response(text: str) -> tuple[str, float]:
    """Pull (label, confidence) out of a classifier completion.

    Tolerant of the cosmetic variation real models produce (surrounding
    brackets, case, hyphens vs underscores, extra prose around the two
    lines), strict about the result: a label outside `TAXONOMY` is not
    silently coerced to a neighbour, it becomes `UNKNOWN_LABEL` at
    confidence 0.0 so the document goes to a human.
    """
    label_match = _LABEL_RE.search(text or "")
    if not label_match:
        return UNKNOWN_LABEL, 0.0

    label = label_match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
    if label not in TAXONOMY:
        return UNKNOWN_LABEL, 0.0

    confidence_match = _CONFIDENCE_RE.search(text)
    if not confidence_match:
        # A label with no stated confidence is not trustworthy on its own.
        return label, 0.0
    confidence = max(0.0, min(1.0, float(confidence_match.group(1))))
    return label, round(confidence, 4)


def classify_document(
    document_text: str,
    *,
    provider: LLMProvider | None = None,
) -> ClassificationResult:
    """Classify `document_text` into the platform taxonomy.

    Never raises: a provider outage or a nonsense response degrades to
    `UNKNOWN_LABEL` at confidence 0.0, which `needs_review` reports as
    review-worthy. Ingestion must not fail because classification did.
    """
    if not document_text.strip():
        return ClassificationResult(
            label=UNKNOWN_LABEL,
            confidence=0.0,
            taxonomy_version=TAXONOMY_VERSION,
            method="skipped",
            error="Document has no text to classify.",
        )

    provider = provider or get_llm_provider()
    prompt = build_classification_prompt(document_text)
    try:
        completion = provider.complete(prompt, max_tokens=32)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        return ClassificationResult(
            label=UNKNOWN_LABEL,
            confidence=0.0,
            taxonomy_version=TAXONOMY_VERSION,
            method="failed",
            error=f"Classifier call failed: {exc}",
        )

    label, confidence = parse_classification_response(completion.text)
    return ClassificationResult(
        label=label,
        confidence=confidence,
        taxonomy_version=TAXONOMY_VERSION,
        method=provider.name,
        usage=completion,
        error=None if label != UNKNOWN_LABEL else "Classifier returned no usable label.",
    )
