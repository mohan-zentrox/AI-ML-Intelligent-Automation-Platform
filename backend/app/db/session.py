"""Database engine/session setup + first-run seed data.

Uses `DATABASE_URL` from settings. Defaults to a local SQLite file so the
backend runs with zero external services; docker-compose wires a real
PostgreSQL instance via DATABASE_URL for anything beyond solo dev/testing.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (dev/test convenience). Production deployments
    should use `alembic upgrade head` instead - see backend/alembic/.
    """
    from app.db.base import Base

    Base.metadata.create_all(bind=engine)


def seed_reference_data() -> None:
    """Seed the fixed T6-* team roster referenced in the FRD/TEAM docs.

    Idempotent: safe to call on every startup. Passwords are placeholders
    for local development ONLY (see docs/TEAM.md) and must never be reused
    for a real deployment.
    """
    from app.core.security import Role, hash_password
    from app.models.user import User

    seed_users = [
        ("T6-LEAD", "T6-LEAD@synapse.local", Role.ADMIN),
        ("T6-BE1", "T6-BE1@synapse.local", Role.WORKFLOW_BUILDER),
        ("T6-DEV1", "T6-DEV1@synapse.local", Role.REVIEWER),
        ("T6-DATA1", "T6-DATA1@synapse.local", Role.ANALYST),
        ("T6-DATA2", "T6-DATA2@synapse.local", Role.ANALYST),
        ("T6-DATA3", "T6-DATA3@synapse.local", Role.API_CONSUMER),
    ]

    with SessionLocal() as db:
        for role_id, email, role in seed_users:
            existing = db.query(User).filter_by(email=email).first()
            if existing:
                continue
            db.add(
                User(
                    role_id=role_id,
                    email=email,
                    hashed_password=hash_password("ChangeMe123!"),
                    role=role.value,
                    is_active=True,
                )
            )
        db.commit()
