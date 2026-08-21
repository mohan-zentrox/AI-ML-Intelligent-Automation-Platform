"""Document classification tests - app/services/classification.py (FRD 7).

Two layers are covered here:

  * the pure classifier (prompt construction, response parsing, confidence,
    degradation to `unknown`), which is deterministic under MockProvider and
    so can be asserted exactly; and
  * the ingestion integration (label persisted, usage logged, low-confidence
    documents queued for a human).

Everything runs offline against MockProvider - see tests/conftest.py.
"""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.models.document import ClassificationStatus, Document
from app.models.review_item import ReviewItem, ReviewItemType, ReviewStatus
from app.models.usage_log import UsageLog
from app.services.classification import (
    TAXONOMY,
    TAXONOMY_VERSION,
    UNKNOWN_LABEL,
    build_classification_prompt,
    classify_document,
    parse_classification_response,
)
from app.services.ingestion import ingest_document
from app.services.llm_provider import CompletionResult, LLMProvider

INVOICE_TEXT = (
    "INVOICE #INV-2291\n"
    "Bill To: Acme Corp\n"
    "Line items: 3 units of consulting at a unit price of 500.00\n"
    "Subtotal 1500.00, sales tax 120.00, total amount due 1620.00.\n"
    "Payment terms: net 30. Remittance to account 88213. Purchase order PO-4471."
)

CONTRACT_TEXT = (
    "MASTER SERVICES AGREEMENT\n"
    "This agreement is entered into by the parties on the effective date below. "
    "The term and termination provisions, confidentiality obligations, warranties, "
    "limitation of liability and indemnification survive expiry. "
    "Governing law: Delaware. Executed signature of each counterparty is required."
)

# Matches no category's vocabulary, so the classifier has nothing to go on.
UNCLASSIFIABLE_TEXT = "The quick brown fox jumps over the lazy dog. Again and again."


class _StubProvider(LLMProvider):
    """Returns a canned completion, for asserting how classification handles
    responses a real provider might produce."""

    name = "stub"

    def __init__(self, text: str) -> None:
        self.text = text

    def embed(self, texts):  # pragma: no cover - classification never embeds
        raise NotImplementedError

    def complete(self, prompt: str, *, max_tokens: int = 512) -> CompletionResult:
        return CompletionResult(
            text=self.text,
            model="stub-v1",
            provider=self.name,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cost_usd=0.0,
            latency_ms=0.0,
        )


class _ExplodingProvider(LLMProvider):
    name = "exploding"

    def embed(self, texts):  # pragma: no cover
        raise NotImplementedError

    def complete(self, prompt: str, *, max_tokens: int = 512) -> CompletionResult:
        raise RuntimeError("provider is down")


# --------------------------------------------------------------------------
# Prompt + parsing
# --------------------------------------------------------------------------


def test_prompt_lists_every_taxonomy_label_and_the_document():
    prompt = build_classification_prompt(INVOICE_TEXT)
    for label in TAXONOMY:
        assert f"[{label}]" in prompt
    assert "INVOICE #INV-2291" in prompt
    assert "CANDIDATE LABELS:" in prompt


def test_prompt_truncates_long_documents_to_the_configured_sample(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "CLASSIFICATION_SAMPLE_CHARS", 50)
    prompt = build_classification_prompt("x" * 5000)
    assert "x" * 50 in prompt
    assert "x" * 51 not in prompt


@pytest.mark.parametrize(
    "response,expected_label,expected_confidence",
    [
        ("LABEL: invoice\nCONFIDENCE: 0.91", "invoice", 0.91),
        # Cosmetic variation a real model produces: brackets, casing, hyphens,
        # and surrounding prose.
        ("LABEL: [Invoice]\nCONFIDENCE: 0.5", "invoice", 0.5),
        ("LABEL: support-ticket\nCONFIDENCE: 0.7", "support_ticket", 0.7),
        ("Sure!\nLABEL: policy\nCONFIDENCE: 0.8\nHope that helps.", "policy", 0.8),
        # Out-of-range confidence is clamped, not trusted verbatim.
        ("LABEL: report\nCONFIDENCE: 4.2", "report", 1.0),
    ],
)
def test_parse_accepts_realistic_response_variation(response, expected_label, expected_confidence):
    label, confidence = parse_classification_response(response)
    assert label == expected_label
    assert confidence == expected_confidence


@pytest.mark.parametrize(
    "response",
    [
        "LABEL: tax_return\nCONFIDENCE: 0.99",  # not in the taxonomy
        "I think this is an invoice.",  # no structured label at all
        "",
    ],
)
def test_parse_degrades_to_unknown_rather_than_guessing(response):
    """An off-taxonomy or unparseable answer must not be coerced onto a
    neighbouring label - it has to reach a human instead."""
    label, confidence = parse_classification_response(response)
    assert label == UNKNOWN_LABEL
    assert confidence == 0.0


def test_parse_treats_a_label_without_confidence_as_untrusted():
    label, confidence = parse_classification_response("LABEL: invoice")
    assert label == "invoice"
    assert confidence == 0.0


# --------------------------------------------------------------------------
# classify_document
# --------------------------------------------------------------------------


def test_classifies_a_clear_invoice_confidently(mock_provider):
    result = classify_document(INVOICE_TEXT, provider=mock_provider)
    assert result.label == "invoice"
    assert result.confidence > get_settings().CLASSIFICATION_REVIEW_THRESHOLD
    assert result.needs_review is False
    assert result.taxonomy_version == TAXONOMY_VERSION
    assert result.usage is not None  # so ingestion can bill the call


def test_classifies_a_clear_contract_confidently(mock_provider):
    result = classify_document(CONTRACT_TEXT, provider=mock_provider)
    assert result.label == "contract"
    assert result.needs_review is False


def test_document_matching_nothing_is_unknown_and_needs_review(mock_provider):
    result = classify_document(UNCLASSIFIABLE_TEXT, provider=mock_provider)
    assert result.label == UNKNOWN_LABEL
    assert result.confidence == 0.0
    assert result.needs_review is True


def test_document_matching_two_categories_lands_below_the_review_threshold(mock_provider):
    """Ambiguity is the case human review exists for: a text pulling equally
    towards invoice and contract must not be labelled confidently."""
    mixed = (
        "This agreement invoice covers the total amount due under the contract "
        "terms and the payment obligations of both parties."
    )
    result = classify_document(mixed, provider=mock_provider)
    assert result.confidence < get_settings().CLASSIFICATION_REVIEW_THRESHOLD
    assert result.needs_review is True


def test_empty_document_is_skipped_without_a_provider_call(mock_provider):
    result = classify_document("   ", provider=mock_provider)
    assert result.label == UNKNOWN_LABEL
    assert result.method == "skipped"
    assert result.usage is None


def test_provider_failure_degrades_instead_of_raising():
    """A classifier outage must not be able to fail an ingestion."""
    result = classify_document(INVOICE_TEXT, provider=_ExplodingProvider())
    assert result.label == UNKNOWN_LABEL
    assert result.confidence == 0.0
    assert result.method == "failed"
    assert result.error is not None
    assert result.needs_review is True


def test_low_confidence_from_the_provider_is_respected(monkeypatch):
    """Confidence comes from the model, not from us second-guessing it."""
    settings = get_settings()
    monkeypatch.setattr(settings, "CLASSIFICATION_REVIEW_THRESHOLD", 0.55)
    result = classify_document(
        INVOICE_TEXT, provider=_StubProvider("LABEL: invoice\nCONFIDENCE: 0.20")
    )
    assert result.label == "invoice"
    assert result.confidence == 0.2
    assert result.needs_review is True


# --------------------------------------------------------------------------
# Ingestion integration
# --------------------------------------------------------------------------


def _ingest(db_session, mock_provider, in_memory_store, title, text):
    return ingest_document(
        db_session,
        title=title,
        raw_text=text,
        source_type="text",
        uploaded_by="user-1",
        provider=mock_provider,
        vector_store=in_memory_store,
    )


def test_ingestion_stores_a_confident_label_without_queueing_review(
    db_session, mock_provider, in_memory_store
):
    document = _ingest(db_session, mock_provider, in_memory_store, "Invoice 2291", INVOICE_TEXT)

    stored = db_session.query(Document).filter_by(id=document.id).first()
    assert stored.classification_label == "invoice"
    assert stored.classification_status == ClassificationStatus.AUTO.value
    assert stored.taxonomy_version == TAXONOMY_VERSION
    assert stored.classified_at is not None
    assert db_session.query(ReviewItem).count() == 0


def test_ingestion_queues_review_for_an_unclassifiable_document(
    db_session, mock_provider, in_memory_store
):
    document = _ingest(
        db_session, mock_provider, in_memory_store, "Mystery", UNCLASSIFIABLE_TEXT
    )

    stored = db_session.query(Document).filter_by(id=document.id).first()
    # Provisional, not labelled: an unusable label is stored as NULL so it
    # cannot be mistaken for a real category by downstream routing.
    assert stored.classification_label is None
    assert stored.classification_status == ClassificationStatus.PENDING_REVIEW.value

    item = db_session.query(ReviewItem).one()
    assert item.item_type == ReviewItemType.CLASSIFICATION.value
    assert item.document_id == document.id
    assert item.status == ReviewStatus.PENDING.value
    assert item.proposed_answer == UNKNOWN_LABEL
    assert item.query_log_id is None


def test_ingestion_logs_classification_cost_to_the_usage_ledger(
    db_session, mock_provider, in_memory_store
):
    _ingest(db_session, mock_provider, in_memory_store, "Invoice 2291", INVOICE_TEXT)

    logs = db_session.query(UsageLog).filter_by(operation="classification").all()
    assert len(logs) == 1
    assert logs[0].provider == "mock"
    assert logs[0].total_tokens > 0


def test_classification_can_be_disabled(db_session, mock_provider, in_memory_store, monkeypatch):
    import app.services.ingestion as ingestion_module

    monkeypatch.setattr(ingestion_module.settings, "CLASSIFICATION_ENABLED", False)
    document = _ingest(db_session, mock_provider, in_memory_store, "Invoice", INVOICE_TEXT)

    stored = db_session.query(Document).filter_by(id=document.id).first()
    assert stored.classification_label is None
    assert stored.classification_status == ClassificationStatus.UNCLASSIFIED.value
    assert db_session.query(UsageLog).filter_by(operation="classification").count() == 0
    # Ingestion itself is unaffected - chunks are still embedded and indexed.
    assert in_memory_store.count() > 0


def test_reclassifying_supersedes_the_previous_pending_review(
    db_session, mock_provider, in_memory_store
):
    """Re-running the classifier must not leave two competing proposals for
    one document sitting in the queue."""
    from app.services.ingestion import classify_and_route

    document = _ingest(
        db_session, mock_provider, in_memory_store, "Mystery", UNCLASSIFIABLE_TEXT
    )
    classify_and_route(db_session, document, actor_id="user-1", provider=mock_provider)

    items = db_session.query(ReviewItem).filter_by(document_id=document.id).all()
    assert len(items) == 2
    pending = [i for i in items if i.status == ReviewStatus.PENDING.value]
    assert len(pending) == 1
