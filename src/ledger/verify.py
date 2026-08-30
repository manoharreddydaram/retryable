"""Walk the ledger and prove — or disprove — that it has not been tampered with.

Recomputes every entry's hash from its stored fields and the previous entry's
stored hash, in sequence order. The first mismatch is reported with its
sequence number; everything before it is proven intact.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ledger.hashing import GENESIS_HASH, compute_hash
from src.ledger.models import LedgerEntry


@dataclass(frozen=True)
class ChainVerificationResult:
    valid: bool
    entries_checked: int
    first_broken_seq: int | None
    reason: str | None


def verify_chain(session: Session) -> ChainVerificationResult:
    entries = session.execute(select(LedgerEntry).order_by(LedgerEntry.seq.asc())).scalars().all()

    expected_prev = GENESIS_HASH
    for checked, entry in enumerate(entries):
        if entry.prev_hash != expected_prev:
            return ChainVerificationResult(
                valid=False,
                entries_checked=checked,
                first_broken_seq=entry.seq,
                reason="prev_hash does not match the previous entry's stored hash",
            )

        fields = {
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "event_type": entry.event_type,
            "actor": entry.actor,
            "payload": entry.payload,
            "created_at": entry.created_at.isoformat(),
        }
        recomputed = compute_hash(entry.prev_hash, fields)
        if recomputed != entry.this_hash:
            return ChainVerificationResult(
                valid=False,
                entries_checked=checked,
                first_broken_seq=entry.seq,
                reason="stored hash does not match the recomputed hash for this entry's fields",
            )

        expected_prev = entry.this_hash

    return ChainVerificationResult(
        valid=True, entries_checked=len(entries), first_broken_seq=None, reason=None
    )
