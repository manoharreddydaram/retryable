"""Polls outbox_entries for eligible rows and executes them against Razorpay.

Rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED so multiple
dispatcher processes could run concurrently without double-processing the
same entry -- not needed at this project's scale, but the correct primitive
for "what if this runs on more than one worker" is one line here, not a
rewrite later.

The circuit breaker is loaded and checked once per row, before any Razorpay
call. If it's open and past cooldown, the first row processed this run gets
the one allowed trial call (half-open); if that call fails, the breaker
reopens and every other eligible row in this run is left pending rather
than each taking its own doomed shot at a service that's still down.

A row that keeps failing doesn't retry forever: past _MAX_ATTEMPTS it's
marked failed_permanently and logged, which is this project's equivalent of
escalating a stuck delivery to a human instead of hammering Razorpay
indefinitely.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.config import Settings
from src.execute.backoff import next_attempt_at
from src.execute.circuit_breaker import (
    BreakerSnapshot,
    before_call,
    record_failure,
    record_success,
    should_allow_call,
)
from src.execute.models import CircuitBreakerState, OutboxEntry
from src.execute.razorpay_client import RazorpayClient, RazorpayClientError
from src.ledger.writer import append_entry
from src.policy.catalog import Intervention

_SERVICE = "razorpay"
_MAX_ATTEMPTS = 10


@dataclass
class DispatchSummary:
    claimed: int = 0
    completed: int = 0
    recovered: int = 0
    failed: int = 0
    failed_permanently: int = 0
    skipped_breaker_open: int = 0
    errors: list[str] = field(default_factory=list)


def run_once(
    session: Session, client: RazorpayClient, settings: Settings, limit: int = 50
) -> DispatchSummary:
    summary = DispatchSummary()
    now = datetime.now(UTC)

    rows = (
        session.execute(
            select(OutboxEntry)
            .where(OutboxEntry.status == "pending", OutboxEntry.next_attempt_at <= now)
            .order_by(OutboxEntry.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )

    for row in rows:
        summary.claimed += 1
        breaker = _load_breaker(session)

        if not should_allow_call(breaker, settings.circuit_breaker_cooldown_seconds, now):
            summary.skipped_breaker_open += 1
            continue

        breaker = before_call(breaker, settings.circuit_breaker_cooldown_seconds, now)
        _save_breaker(session, breaker)

        try:
            result = _execute(client, row)
        except RazorpayClientError as exc:
            row.attempts += 1
            row.last_error = str(exc)
            row.updated_at = now
            breaker = record_failure(breaker, settings.circuit_breaker_failure_threshold, now)
            _save_breaker(session, breaker)

            if row.attempts >= _MAX_ATTEMPTS:
                row.status = "failed_permanently"
                summary.failed_permanently += 1
                _log(
                    session,
                    row,
                    "outbox.failed_permanently",
                    {"error": str(exc), "attempts": row.attempts},
                )
            else:
                row.next_attempt_at = next_attempt_at(row.attempts, now)
                summary.failed += 1
                summary.errors.append(str(exc))
                _log(
                    session,
                    row,
                    "outbox.attempt_failed",
                    {"error": str(exc), "attempts": row.attempts},
                )
            continue

        breaker = record_success(breaker)
        _save_breaker(session, breaker)

        row.status = "complete"
        row.razorpay_payment_link_id = result.id
        row.razorpay_short_url = result.short_url
        row.updated_at = now

        if result.recovered_from_conflict:
            summary.recovered += 1
            _log(session, row, "outbox.recovered_from_conflict", {"payment_link_id": result.id})
        else:
            summary.completed += 1
            _log(
                session,
                row,
                "outbox.completed",
                {"payment_link_id": result.id, "short_url": result.short_url},
            )

    return summary


def _execute(client: RazorpayClient, row: OutboxEntry):
    intervention = Intervention(row.intervention)
    if intervention == Intervention.SEND_PAYMENT_LINK:
        return client.create_payment_link(
            reference_id=row.idempotency_key, amount_paise=row.amount_paise, order_id=row.order_id
        )
    raise NotImplementedError(f"dispatcher has no execution path for {intervention!r} yet")


def _load_breaker(session: Session) -> BreakerSnapshot:
    row = session.get(CircuitBreakerState, _SERVICE)
    if row is None:
        return BreakerSnapshot(state="closed", consecutive_failures=0, opened_at=None)
    return BreakerSnapshot(
        state=row.state, consecutive_failures=row.consecutive_failures, opened_at=row.opened_at
    )


def _save_breaker(session: Session, snapshot: BreakerSnapshot) -> None:
    """An atomic upsert, not get-then-add/update: _save_breaker is called
    twice per outbox entry (before and after the Razorpay call) inside the
    same unflushed transaction. A plain session.get() can't see a row this
    same transaction added moments ago but never flushed, so two calls in a
    row would each conclude "no row exists yet" and both try to insert the
    same primary key. This surfaced for real the first time an eval batch
    processed more than one entry -- the mocked dispatcher tests never
    exercised two saves in the same unflushed transaction."""
    now = datetime.now(UTC)
    stmt = pg_insert(CircuitBreakerState).values(
        service=_SERVICE,
        state=snapshot.state,
        consecutive_failures=snapshot.consecutive_failures,
        opened_at=snapshot.opened_at,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["service"],
        set_={
            "state": stmt.excluded.state,
            "consecutive_failures": stmt.excluded.consecutive_failures,
            "opened_at": stmt.excluded.opened_at,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def _log(session: Session, row: OutboxEntry, event_type: str, payload: dict) -> None:
    append_entry(
        session,
        entity_type="payment",
        entity_id=row.order_id,
        event_type=event_type,
        actor="system:dispatcher",
        payload=payload,
    )
