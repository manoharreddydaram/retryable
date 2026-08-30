"""Computes the DB-dependent parts of a DecisionInput that decide() itself
never touches -- src/policy/engine.py stays a pure function testable
without a database; this module is where "how many times have we actually
reached this payer in the last 7 days" gets answered for real.

Only *completed* outbox entries count as a touch. A decision that resolved
to send_payment_link but never made it to Razorpay hasn't reached the
customer yet, so it doesn't count against them.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.execute.models import OutboxEntry
from src.policy.models import Decision


def touches_in_window(
    session: Session, payer_contact: str | None, window_days: int = 7, now: datetime | None = None
) -> int:
    if not payer_contact:
        return 0
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    count = session.execute(
        select(func.count())
        .select_from(Decision)
        .join(OutboxEntry, OutboxEntry.decision_id == Decision.id)
        .where(
            Decision.payer_contact == payer_contact,
            OutboxEntry.status == "complete",
            OutboxEntry.updated_at >= window_start,
        )
    ).scalar_one()
    return count
