"""SQLAlchemy engine, session factory, and declarative base.

One engine per process, created at import time from `Settings.database_url`.
Every model in the codebase inherits from `Base` so `Base.metadata` is a
complete picture of the schema for Alembic's autogenerate support.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(get_settings().database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Commit/rollback is the route's decision, not this
    function's -- nothing is persisted unless the route explicitly commits."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Import every model module so Base.metadata is complete wherever this
# module is imported -- see src/db/all_models.py. Deliberately at the
# bottom: Base must already exist before those modules import it back.
from src.db import all_models  # noqa: E402, F401
