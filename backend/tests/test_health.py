"""Tests for the /health probe.

`/health` reports `stored_chunks` (database) next to `indexed_chunks` (vector
store) because the two can silently disagree: with
VECTOR_STORE_BACKEND=inmemory a restart drops every embedding while the
document/chunk rows survive, after which the UI still lists documents as
ingested but every query refuses for lack of anything to retrieve.
`retrieval_ready` is the one-glance version of that check.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]

client = TestClient(app)


def test_health_is_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_the_active_backends() -> None:
    body = client.get("/health").json()
    assert body["llm_provider"] == "mock"
    assert body["vector_store_backend"] == "inmemory"


def test_health_degrades_gracefully_when_counts_are_unavailable() -> None:
    """The suite's own DATABASE_URL exercises the fallback path for free.

    `sqlite:///:memory:` hands out a fresh, empty database per connection, and
    TestClient runs sync endpoints on a worker thread - so the chunk query hits
    a connection with no tables and raises. A probe that 500s on a failed
    diagnostic is worse than one that omits the field, so assert it still
    reports healthy.
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def _health_against_a_real_database(tmp_path: Path) -> dict:
    """Fetch /health from a subprocess backed by a file database.

    A file DB is required because the counts read through `SessionLocal` on
    whatever thread serves the request; an in-memory SQLite database is
    per-connection and therefore empty on that thread.
    """
    code = (
        "import json;"
        "from fastapi.testclient import TestClient;"
        "from app.db.session import init_db;"
        "from app.main import app;"
        "init_db();"
        "print(json.dumps(TestClient(app).get('/health').json()))"
    )
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path.as_posix()}/health.db",
        "ENVIRONMENT": "local",
        "SECRET_KEY": "test-secret-key",
        "VECTOR_STORE_BACKEND": "inmemory",
        "LLM_PROVIDER": "mock",
        "SEED_DEMO_USERS": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, "health subprocess failed: " + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_health_exposes_both_chunk_counts(tmp_path: Path) -> None:
    body = _health_against_a_real_database(tmp_path)
    assert isinstance(body["stored_chunks"], int)
    assert isinstance(body["indexed_chunks"], int)


def test_retrieval_ready_on_an_empty_but_working_install(tmp_path: Path) -> None:
    """Nothing stored and nothing indexed is consistent, not degraded."""
    body = _health_against_a_real_database(tmp_path)
    assert body["stored_chunks"] == 0
    assert body["indexed_chunks"] == 0
    assert body["retrieval_ready"] is True


def test_retrieval_ready_is_false_when_the_stores_diverge(tmp_path: Path) -> None:
    """The case that matters: chunk rows survive a restart, vectors do not."""
    code = (
        "import json;"
        "from fastapi.testclient import TestClient;"
        "from app.db.session import SessionLocal, init_db;"
        "from app.models.chunk import Chunk;"
        "from app.main import app;"
        "init_db();"
        "db = SessionLocal();"
        "db.add(Chunk(document_id='doc-1', chunk_index=0, text='orphaned chunk',"
        " token_count=2, embedding='[]', embedding_model='mock'));"
        "db.commit();"
        "db.close();"
        "print(json.dumps(TestClient(app).get('/health').json()))"
    )
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path.as_posix()}/diverged.db",
        "ENVIRONMENT": "local",
        "SECRET_KEY": "test-secret-key",
        "VECTOR_STORE_BACKEND": "inmemory",
        "LLM_PROVIDER": "mock",
        "SEED_DEMO_USERS": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, "divergence subprocess failed: " + result.stderr
    body = json.loads(result.stdout.strip().splitlines()[-1])
    assert body["stored_chunks"] == 1
    assert body["indexed_chunks"] == 0
    assert body["retrieval_ready"] is False
