"""Shared test fixtures.

`db_session` binds a Session to a connection-level transaction and rolls it
back after every test, using SQLAlchemy 2.0's savepoint join mode. This means
a test can call `session.flush()`, run raw SQL, or even trigger a database
error and the fixture still leaves the real database untouched — required
here since Stage 1 tests run against the same Postgres instance `make run`
uses, not a throwaway database.
"""

import pytest
from sqlalchemy.orm import sessionmaker

from src.db.base import engine


@pytest.fixture()
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    session = session_factory()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
