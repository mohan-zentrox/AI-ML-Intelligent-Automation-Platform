"""Model import hub - import this to get a fully-populated `Base.metadata`.

`Base` itself lives in `app.db.base_class` (which imports nothing from
`app.*`). This module re-exports it and then imports every model module so
each one registers itself on `Base.metadata`.

Keeping the two separate is what breaks the import cycle: a model importing
`Base` from *this* module would re-enter it while it was still part-way
through importing that same model. `alembic/env.py`, `init_db()`, and the
test fixtures all import from here because they need every table present.
"""
from app.db.base_class import Base

# Import models for their side effect of registering on Base.metadata.
from app.models.user import User  # noqa: E402,F401
from app.models.api_key import ApiKey  # noqa: E402,F401
from app.models.document import Document  # noqa: E402,F401
from app.models.chunk import Chunk  # noqa: E402,F401
from app.models.query_log import QueryLog  # noqa: E402,F401
from app.models.review_item import ReviewItem  # noqa: E402,F401
from app.models.feedback import Feedback  # noqa: E402,F401
from app.models.usage_log import UsageLog  # noqa: E402,F401

__all__ = [
    "Base",
    "User",
    "ApiKey",
    "Document",
    "Chunk",
    "QueryLog",
    "ReviewItem",
    "Feedback",
    "UsageLog",
]
