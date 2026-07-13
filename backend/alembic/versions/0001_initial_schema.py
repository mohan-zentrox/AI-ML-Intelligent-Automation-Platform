"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("role_id", sa.String(32), unique=True, index=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), index=True, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_prefix", sa.String(16), index=True, nullable=False),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(32), default="text"),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("char_count", sa.Integer, default=0),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), index=True, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, default=0),
        sa.Column("embedding", sa.JSON, nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "query_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("citations", sa.JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("refused", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query_log_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("proposed_answer", sa.Text, nullable=False),
        sa.Column("citations", sa.JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), default="pending"),
        sa.Column("reviewer_id", sa.String(36), nullable=True),
        sa.Column("final_answer", sa.Text, nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("review_item_id", sa.String(36), index=True, nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "usage_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, default=0),
        sa.Column("completion_tokens", sa.Integer, default=0),
        sa.Column("total_tokens", sa.Integer, default=0),
        sa.Column("cost_usd", sa.Float, default=0.0),
        sa.Column("latency_ms", sa.Float, default=0.0),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("usage_logs")
    op.drop_table("feedback")
    op.drop_table("review_items")
    op.drop_table("query_logs")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("api_keys")
    op.drop_table("users")
