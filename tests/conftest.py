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

from src.config import Settings
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


def make_settings(**overrides) -> Settings:
    """A fully-explicit Settings instance for tests, independent of whatever
    is in the developer's local .env -- so a test's outcome depends only on
    what it actually asserts, not on config it never mentions."""
    defaults = {
        "database_url": "postgresql+psycopg://test:test@localhost/test",
        "kill_switch_enabled": False,
        "max_interventions_per_batch": 200,
        "max_touches_per_payer_7d": 3,
        "quiet_hours_start": 21,
        "quiet_hours_end": 9,
        "min_diagnosis_confidence": 0.7,
        "human_approval_threshold_paise": 2_500_000,
        "intervention_cost_paise": 50,
        "circuit_breaker_failure_threshold": 5,
        "circuit_breaker_cooldown_seconds": 60,
    }
    defaults.update(overrides)
    return Settings(**defaults)
