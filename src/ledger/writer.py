"""The only function in this codebase allowed to append to the ledger.

Concurrency note: Stage 2's webhook handlers and Stage 5's outbox dispatcher
will both write to this table from separate transactions. Without
serialisation, two concurrent appends could both read the same "last hash"
and each build a valid-looking entry that forks the chain. A Postgres
advisory lock, held for the transaction, makes appends line up one at a time.

This function does not commit. The caller's transaction decides when the
ledger entry becomes durable, since it is usually written alongside other
rows (a decision, an intervention record) that must land atomically with it.
"""

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.ledger.hashing import GENESIS_HASH, compute_hash
from src.ledger.models import LedgerEntry

_ADVISORY_LOCK_KEY = "retryable.ledger.append"


def append_entry(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor: str,
    payload: dict,
) -> LedgerEntry:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": _ADVISORY_LOCK_KEY}
    )

    prev_hash = (
        session.execute(
            select(LedgerEntry.this_hash).order_by(LedgerEntry.seq.desc()).limit(1)
        ).scalar_one_or_none()
        or GENESIS_HASH
    )

    created_at = datetime.now(UTC)
    fields = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "actor": actor,
        "payload": payload,
        "created_at": created_at.isoformat(),
    }
    this_hash = compute_hash(prev_hash, fields)

    entry = LedgerEntry(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor=actor,
        payload=payload,
        created_at=created_at,
        prev_hash=prev_hash,
        this_hash=this_hash,
    )
    session.add(entry)
    session.flush()
    return entry
