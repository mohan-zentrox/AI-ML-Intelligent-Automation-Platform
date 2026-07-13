"""Shared pytest fixtures.

Everything here runs against:
  - LLM_PROVIDER=mock (deterministic, offline - see app/services/llm_provider.py)
  - VECTOR_STORE_BACKEND=inmemory (zero-dependency - see app/services/vector_store.py)
  - DATABASE_URL=sqlite (in-memory, one fresh DB per test)

This means the full test suite has zero external dependencies: no network,
no Postgres, no ChromaDB, no API keys. That's intentional - see README.md
"Verification" section for why this is the sandbox-safe path.
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("VECTOR_STORE_BACKEND", "inmemory")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import Role, create_access_token, hash_password
from app.db.base import Base
from app.models.user import User
from app.services.llm_provider import MockProvider
from app.services.vector_store import InMemoryVectorStore


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture()
def in_memory_store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture()
def seeded_admin(db_session) -> User:
    user = User(
        role_id="T6-LEAD",
        email="T6-LEAD@synapse.example",
        hashed_password=hash_password("ChangeMe123!"),
        role=Role.ADMIN.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_token(seeded_admin) -> str:
    return create_access_token(subject=seeded_admin.id, role=seeded_admin.role)
