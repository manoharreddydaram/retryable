"""GET /api/ledger -- paginated, newest-first view of the hash-chained
audit log. GET /api/ledger/verify -- runs the same verify_chain() proof
Stage 1 built, on demand, so the Audit Ledger screen can show the chain is
provably intact rather than merely asserting it.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import ChainVerification, LedgerEntrySummary, LedgerPage
from src.db.base import get_db
from src.ledger.models import LedgerEntry
from src.ledger.verify import verify_chain

router = APIRouter()


@router.get("/api/ledger", response_model=LedgerPage)
def list_ledger(
    limit: int = 50,
    before_seq: int | None = None,
    session: Session = Depends(get_db),  # noqa: B008 -- FastAPI's DI mechanism
) -> LedgerPage:
    query = select(LedgerEntry).order_by(LedgerEntry.seq.desc())
    if before_seq is not None:
        query = query.where(LedgerEntry.seq < before_seq)
    rows = session.execute(query.limit(limit)).scalars().all()

    entries = [
        LedgerEntrySummary(
            seq=e.seq,
            entry_id=e.entry_id,
            created_at=e.created_at,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            event_type=e.event_type,
            actor=e.actor,
            payload=e.payload,
            prev_hash=e.prev_hash,
            this_hash=e.this_hash,
        )
        for e in rows
    ]
    next_before_seq = entries[-1].seq if len(entries) == limit else None
    return LedgerPage(entries=entries, next_before_seq=next_before_seq)


@router.get("/api/ledger/verify", response_model=ChainVerification)
def get_chain_verification(
    session: Session = Depends(get_db),  # noqa: B008 -- FastAPI's DI mechanism
) -> ChainVerification:
    result = verify_chain(session)
    return ChainVerification(
        valid=result.valid,
        entries_checked=result.entries_checked,
        first_broken_seq=result.first_broken_seq,
        reason=result.reason,
    )
