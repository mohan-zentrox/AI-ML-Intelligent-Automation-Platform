"""SQLAlchemy declarative base + model import hub.

alembic/env.py imports `Base.metadata` from this module for autogeneration,
so every model module must be imported here even if unused directly.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models so they register on Base.metadata. Keep at bottom to avoid
# circular imports (models import Base from this module).
from app.models.user import User  # noqa: E402,F401
from app.models.api_key import ApiKey  # noqa: E402,F401
from app.models.document import Document  # noqa: E402,F401
from app.models.chunk import Chunk  # noqa: E402,F401
from app.models.query_log import QueryLog  # noqa: E402,F401
from app.models.review_item import ReviewItem  # noqa: E402,F401
from app.models.feedback import Feedback  # noqa: E402,F401
from app.models.usage_log import UsageLog  # noqa: E402,F401
