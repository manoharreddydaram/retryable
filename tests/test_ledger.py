"""Ledger tests against a real Postgres instance (see tests/conftest.py).

Covers three separate guarantees:
  1. append_entry() correctly chains new entries to the previous hash.
  2. verify_chain() detects a corrupted entry instead of silently passing.
  3. Postgres itself refuses UPDATE/DELETE on the table, independent of (1) and (2).
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from src.ledger.hashing import GENESIS_HASH
from src.ledger.models import LedgerEntry
from src.ledger.verify import verify_chain
from src.ledger.writer import append_entry


def _append(session, note: str = "x") -> LedgerEntry:
    return append_entry(
        session,
        entity_type="payment",
        entity_id="pay_test123",
        event_type="payment.failed",
        actor="system",
        payload={"note": note},
    )


def test_append_chains_to_whatever_the_ledger_s_current_last_hash_is(db_session) -> None:
    """Not assumed to be GENESIS_HASH: this database also serves real eval
    and dispatch runs (see conftest.py), which may have already appended
    real entries before this test ever runs. GENESIS_HASH itself -- the
    behaviour on a truly empty chain -- is covered independently in
    test_hashing.py, which needs no database at all."""
    prior_last_hash = (
        db_session.execute(
            select(LedgerEntry.this_hash).order_by(LedgerEntry.seq.desc()).limit(1)
        ).scalar_one_or_none()
        or GENESIS_HASH
    )

    entry = _append(db_session)

    assert entry.prev_hash == prior_last_hash
    assert entry.seq is not None


def test_second_entry_chains_to_first(db_session) -> None:
    first = _append(db_session, "first")
    second = _append(db_session, "second")
    assert second.prev_hash == first.this_hash
    assert second.seq == first.seq + 1


def test_verify_chain_valid_on_untouched_chain(db_session) -> None:
    before = verify_chain(db_session)
    assert before.valid is True  # whatever's already in this database must itself be intact

    for i in range(5):
        _append(db_session, f"entry-{i}")

    result = verify_chain(db_session)
    assert result.valid is True
    assert result.entries_checked == before.entries_checked + 5
    assert result.first_broken_seq is None


def test_verify_chain_detects_a_corrupted_entry(db_session) -> None:
    _append(db_session, "good-1")
    _append(db_session, "good-2")

    # Insert a row directly, bypassing append_entry, with a hash that does not
    # match its own fields -- simulating corruption rather than the writer's
    # own (correct) behaviour.
    bad = LedgerEntry(
        entry_id=uuid.uuid4(),
        created_at=db_session.execute(text("SELECT now()")).scalar(),
        entity_type="payment",
        entity_id="pay_test123",
        event_type="payment.failed",
        actor="system",
        payload={"note": "corrupted"},
        prev_hash="f" * 64,
        this_hash="0" * 64,
    )
    db_session.add(bad)
    db_session.flush()

    result = verify_chain(db_session)
    assert result.valid is False
    assert result.first_broken_seq == bad.seq


def test_database_rejects_update(db_session) -> None:
    entry = _append(db_session)

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("UPDATE ledger_entries SET actor = 'tampered' WHERE seq = :seq"),
            {"seq": entry.seq},
        )
        db_session.flush()
    db_session.rollback()


def test_database_rejects_delete(db_session) -> None:
    entry = _append(db_session)

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(text("DELETE FROM ledger_entries WHERE seq = :seq"), {"seq": entry.seq})
        db_session.flush()
    db_session.rollback()
