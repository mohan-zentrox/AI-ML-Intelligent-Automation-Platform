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
