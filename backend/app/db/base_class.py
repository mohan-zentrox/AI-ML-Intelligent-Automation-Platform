"""SQLAlchemy declarative base.

Deliberately contains *only* the `Base` class and imports nothing from
`app.*`. Model modules import `Base` from here, never from `app.db.base`,
because `app.db.base` imports every model module in turn to register it on
`Base.metadata` - importing that hub from a model would be a cycle.

    app.models.*      -> app.db.base_class   (leaf, no app imports)
    app.db.base       -> app.db.base_class + every app.models.*  (the hub)

Import `app.db.base` when you need a fully-populated `Base.metadata`
(alembic autogenerate, `create_all`); import this module when you only need
the base class to declare a model against.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
