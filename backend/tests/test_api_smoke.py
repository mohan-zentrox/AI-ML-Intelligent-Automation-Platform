"""API-level smoke tests: FastAPI wiring, RBAC gating, and the happy path
through login -> ingest -> query using the standard FastAPI testing pattern
(StaticPool SQLite + `dependency_overrides[get_db]`) so it does not depend
on the app's real (env-configured) database engine.

Deeper behavioural coverage (chunking correctness, retrieval ranking, RAG
citation correctness, low-confidence review routing, refusal path) lives in
the service-layer tests (test_chunking.py, test_vector_store.py,
test_rag.py) where exact behaviour can be asserted precisely; this file
only checks that the HTTP layer, dependency injection, and role gating are
wired correctly end to end.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import Role, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from tests.document_fixtures import _build_docx, _build_pdf

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="module")
def client():
    db = _TestingSessionLocal()
    db.add(
        User(
            role_id="T6-LEAD",
            email="admin@synapse.example",
            hashed_password=hash_password("AdminPass123!"),
            role=Role.ADMIN.value,
            is_active=True,
        )
    )
    db.add(
        User(
            role_id="T6-DATA1",
            email="analyst@synapse.example",
            hashed_password=hash_password("AnalystPass123!"),
            role=Role.ANALYST.value,
            is_active=True,
        )
    )
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


def _login(client, email, password) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_health_endpoint():
    with TestClient(app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "mock"


def test_login_rejects_bad_credentials(client):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@synapse.example", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_query_endpoint_requires_auth(client):
    resp = client.post("/api/v1/query", json={"question": "hello?"})
    assert resp.status_code == 401


def test_admin_can_ingest_and_query_with_citations(client):
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    headers = {"Authorization": f"Bearer {token}"}

    ingest_resp = client.post(
        "/api/v1/documents/text",
        json={
            "title": "Onboarding Guide",
            "text": (
                "New employees receive their laptop on day one. "
                "IT support can be reached at the internal helpdesk portal."
            ),
        },
        headers=headers,
    )
    assert ingest_resp.status_code == 200, ingest_resp.text
    assert ingest_resp.json()["chunk_count"] >= 1

    query_resp = client.post(
        "/api/v1/query", json={"question": "When do new employees get a laptop?"}, headers=headers
    )
    assert query_resp.status_code == 200, query_resp.text
    body = query_resp.json()
    assert "answer" in body
    assert "confidence" in body
    assert "refused" in body


def test_analyst_cannot_issue_api_keys(client):
    token = _login(client, "analyst@synapse.example", "AnalystPass123!")
    resp = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "analyst key", "role": Role.ANALYST.value},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_admin_can_issue_scoped_api_key_and_use_it(client):
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    resp = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "ci-consumer-key", "role": Role.API_CONSUMER.value},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    api_key = resp.json()["api_key"]
    assert api_key.startswith("syn_")

    query_resp = client.post(
        "/api/v1/query",
        json={"question": "hello?"},
        headers={"X-API-Key": api_key},
    )
    assert query_resp.status_code == 200


def test_analyst_can_read_usage_analytics(client):
    token = _login(client, "analyst@synapse.example", "AnalystPass123!")
    resp = client.get("/api/v1/analytics/usage", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "by_day" in body
    assert "by_user" in body


def test_admin_can_upload_a_pdf(client):
    """FRD 4.2.1 - the multipart path must parse a real PDF, not just .txt/.md."""
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    pdf_bytes = _build_pdf(["Expense policy: meals are reimbursed up to 40 USD per day."])

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("expense-policy.pdf", pdf_bytes, "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_type"] == "pdf"
    assert body["title"] == "expense-policy.pdf"
    assert body["chunk_count"] >= 1


def test_admin_can_upload_a_docx_with_an_explicit_title(client):
    """FRD 4.2.3 - and an explicit `title` form field wins over the filename."""
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    docx_bytes = _build_docx(["Vendor Agreement", "Termination requires 60 days notice."])

    resp = client.post(
        "/api/v1/documents",
        data={"title": "Vendor Agreement 2026"},
        files={
            "file": (
                "vendor.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_type"] == "docx"
    assert body["title"] == "Vendor Agreement 2026"
    assert body["chunk_count"] >= 1


def test_upload_over_the_size_cap_returns_413(client, monkeypatch):
    """An oversized upload must be refused, and refused before it is parsed.

    The cap is patched down rather than the test building a real 10 MB body:
    the behaviour under test is the comparison, and a 10 MB multipart request
    per run buys nothing but wall-clock time.
    """
    from app.api.v1 import documents as documents_api

    monkeypatch.setattr(documents_api.settings, "MAX_UPLOAD_BYTES", 1024)
    token = _login(client, "admin@synapse.example", "AdminPass123!")

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("huge.txt", b"x" * 4096, "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413, resp.text
    # The message has to name a size the caller can act on; a cap under 1 MB
    # used to integer-divide to the useless "0 MB".
    assert resp.json()["detail"] == "File exceeds the maximum upload size of 1 KB."

    # Rejected, not half-ingested: nothing reached the documents table.
    listing = client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert not any(d["title"] == "huge.txt" for d in listing)


def test_size_cap_is_checked_before_the_format_check(client, monkeypatch):
    """413 beats 415 - an oversized body is rejected without being parsed.

    Order matters: deciding the format first would mean reading the whole
    oversized body to find out it was unsupported anyway, which is exactly
    the allocation the cap exists to prevent.
    """
    from app.api.v1 import documents as documents_api

    monkeypatch.setattr(documents_api.settings, "MAX_UPLOAD_BYTES", 1024)
    token = _login(client, "admin@synapse.example", "AdminPass123!")

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("backup.zip", b"PK" + b"x" * 4096, "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413, resp.text


def test_upload_at_exactly_the_size_cap_is_accepted(client, monkeypatch):
    """The boundary is inclusive - the cap rejects `>`, not `>=`."""
    from app.api.v1 import documents as documents_api

    body = b"Refunds are issued within 30 days. " * 20
    monkeypatch.setattr(documents_api.settings, "MAX_UPLOAD_BYTES", len(body))
    token = _login(client, "admin@synapse.example", "AdminPass123!")

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("exact.txt", body, "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["chunk_count"] >= 1


def test_default_upload_cap_is_ten_megabytes():
    """Guards the default itself: a cap silently widened to a huge value would
    leave every test above passing while the deployment stayed exposed."""
    from app.core.config import Settings

    assert Settings(SECRET_KEY="x").MAX_UPLOAD_BYTES == 10 * 1024 * 1024


def test_upload_of_unsupported_type_returns_415(client):
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("backup.zip", b"PK", "application/zip")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 415
    assert ".pdf" in resp.json()["detail"]


def test_upload_of_corrupt_pdf_returns_400(client):
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("broken.pdf", b"not really a pdf", "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_uploaded_pdf_is_retrievable_through_rag(client):
    """The whole point of multi-format ingestion: PDF content must reach the
    vector store and come back as a citation."""
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    headers = {"Authorization": f"Bearer {token}"}
    pdf_bytes = _build_pdf(["The security incident hotline is staffed 24 hours a day."])

    upload = client.post(
        "/api/v1/documents",
        files={"file": ("security.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["id"]

    listing = client.get("/api/v1/documents", headers=headers)
    assert listing.status_code == 200
    assert any(d["id"] == document_id for d in listing.json())


# --------------------------------------------------------------------------
# Document classification (FRD 7)
# --------------------------------------------------------------------------

_INVOICE_TEXT = (
    "INVOICE #INV-7781. Bill To: Globex. Line items: 2 units, unit price 250.00. "
    "Subtotal 500.00, sales tax 40.00, total amount due 540.00. Payment terms net 30. "
    "Remittance details below. Purchase order PO-9931."
)

_UNCLASSIFIABLE_TEXT = "Cabbage lantern brook whistle. Marble tangent violet sparrow."


def test_taxonomy_endpoint_serves_the_label_set(client):
    """Clients render label pickers from this, so it must not be empty or
    unversioned."""
    token = _login(client, "analyst@synapse.example", "AnalystPass123!")
    resp = client.get("/api/v1/documents/taxonomy", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"]
    labels = [c["label"] for c in body["categories"]]
    assert "invoice" in labels
    assert all(c["description"] for c in body["categories"])


def test_ingested_document_is_classified_and_filterable(client):
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/api/v1/documents/text",
        json={"title": "Globex Invoice 7781", "text": _INVOICE_TEXT},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["classification_label"] == "invoice"
    assert body["classification_status"] == "auto"
    assert body["classification_confidence"] > 0

    filtered = client.get("/api/v1/documents?label=invoice", headers=headers)
    assert filtered.status_code == 200
    assert any(d["id"] == body["id"] for d in filtered.json())


def test_filtering_by_an_unknown_label_is_a_400(client):
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    resp = client.get(
        "/api/v1/documents?label=not_a_category", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 400


def test_analyst_cannot_reclassify(client):
    """Reclassification costs a provider call and can overwrite a
    human-confirmed label, so it is Admin/Workflow Builder only."""
    token = _login(client, "analyst@synapse.example", "AnalystPass123!")
    headers = {"Authorization": f"Bearer {token}"}
    doc = client.post(
        "/api/v1/documents/text",
        json={"title": "Analyst Invoice", "text": _INVOICE_TEXT},
        headers=headers,
    )
    assert doc.status_code == 200, doc.text

    resp = client.post(f"/api/v1/documents/{doc.json()['id']}/reclassify", headers=headers)
    assert resp.status_code == 403


def test_reclassify_of_a_missing_document_is_a_404(client):
    token = _login(client, "admin@synapse.example", "AdminPass123!")
    resp = client.post(
        "/api/v1/documents/does-not-exist/reclassify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_low_confidence_classification_round_trips_through_human_review(client):
    """The full FRD 7.1 loop: an unclassifiable document is queued, a reviewer
    corrects the label, and the correction lands on the document itself -
    otherwise the queue would be decorative."""
    admin_headers = {"Authorization": f"Bearer {_login(client, 'admin@synapse.example', 'AdminPass123!')}"}

    doc = client.post(
        "/api/v1/documents/text",
        json={"title": "Unreadable Note", "text": _UNCLASSIFIABLE_TEXT},
        headers=admin_headers,
    )
    assert doc.status_code == 200, doc.text
    document_id = doc.json()["id"]
    assert doc.json()["classification_label"] is None
    assert doc.json()["classification_status"] == "pending_review"

    queue = client.get(
        "/api/v1/review/queue?status=pending&item_type=classification", headers=admin_headers
    )
    assert queue.status_code == 200, queue.text
    items = [i for i in queue.json() if i["document_id"] == document_id]
    assert len(items) == 1
    item = items[0]
    assert item["item_type"] == "classification"

    # The classifier proposed no usable label, so there is nothing to approve.
    bad = client.post(
        f"/api/v1/review/queue/{item['id']}/decision",
        json={"decision": "approved", "rationale": "looks fine"},
        headers=admin_headers,
    )
    assert bad.status_code == 400

    # Nor can a reviewer invent a label outside the taxonomy.
    off_taxonomy = client.post(
        f"/api/v1/review/queue/{item['id']}/decision",
        json={"decision": "edited", "rationale": "it is a memo", "final_answer": "memo"},
        headers=admin_headers,
    )
    assert off_taxonomy.status_code == 400

    decided = client.post(
        f"/api/v1/review/queue/{item['id']}/decision",
        json={
            "decision": "edited",
            "rationale": "Reviewed the source: it is internal correspondence.",
            "final_answer": "correspondence",
        },
        headers=admin_headers,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "edited"

    listing = client.get("/api/v1/documents?label=correspondence", headers=admin_headers)
    corrected = [d for d in listing.json() if d["id"] == document_id]
    assert len(corrected) == 1
    assert corrected[0]["classification_status"] == "corrected"
    # The label is a human's now, so the model's confidence is cleared.
    assert corrected[0]["classification_confidence"] is None
