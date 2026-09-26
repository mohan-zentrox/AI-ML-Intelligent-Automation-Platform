"""document classification (FRD 7)

Adds the classification columns on `documents`, and generalises
`review_items` so one queue carries both low-confidence RAG answers and
low-confidence classifications:

  * `review_items.item_type`     - "answer" | "classification"
  * `review_items.document_id`   - back-reference for classification items
  * `review_items.query_log_id`  - relaxed to nullable, since classification
                                   items have no originating query

Batch mode is used throughout because SQLite (the zero-dependency local
default, see backend/app/db/session.py) cannot ALTER a column in place.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("classification_label", sa.String(64), nullable=True))
        batch.add_column(sa.Column("classification_confidence", sa.Float, nullable=True))
        batch.add_column(
            sa.Column(
                "classification_status",
                sa.String(16),
                nullable=False,
                server_default="unclassified",
            )
        )
        batch.add_column(sa.Column("taxonomy_version", sa.String(16), nullable=True))
        batch.add_column(sa.Column("classified_at", sa.DateTime, nullable=True))
    op.create_index(
        "ix_documents_classification_label", "documents", ["classification_label"]
    )

    with op.batch_alter_table("review_items") as batch:
        batch.add_column(
            sa.Column("item_type", sa.String(16), nullable=False, server_default="answer")
        )
        batch.add_column(sa.Column("document_id", sa.String(36), nullable=True))
        batch.alter_column("query_log_id", existing_type=sa.String(36), nullable=True)
    op.create_index("ix_review_items_item_type", "review_items", ["item_type"])


def downgrade() -> None:
    op.drop_index("ix_review_items_item_type", table_name="review_items")
    with op.batch_alter_table("review_items") as batch:
        # Pre-0002 rows are all answer items, so any classification item has
        # no valid query_log_id to restore - drop them before re-imposing the
        # NOT NULL constraint.
        batch.drop_column("document_id")
        batch.drop_column("item_type")
    op.execute("DELETE FROM review_items WHERE query_log_id IS NULL")
    with op.batch_alter_table("review_items") as batch:
        batch.alter_column("query_log_id", existing_type=sa.String(36), nullable=False)

    op.drop_index("ix_documents_classification_label", table_name="documents")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("classified_at")
        batch.drop_column("taxonomy_version")
        batch.drop_column("classification_status")
        batch.drop_column("classification_confidence")
        batch.drop_column("classification_label")
