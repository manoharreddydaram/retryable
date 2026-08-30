"""A three-state circuit breaker (closed / open / half-open) for the
Razorpay client, kept as a pure state machine over a plain snapshot so its
transition logic is testable without a database. src/execute/dispatcher.py
is responsible for loading and persisting a CircuitBreakerState row around
calls to these functions.

closed: calls go through normally.
open: calls are refused outright until the cooldown elapses -- no point
      hammering a service that's already down.
half_open: exactly one trial call is allowed through; its result decides
      whether the breaker recloses or reopens.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class BreakerSnapshot:
    state: str  # "closed" | "open" | "half_open"
    consecutive_failures: int
    opened_at: datetime | None


def should_allow_call(
    snapshot: BreakerSnapshot, cooldown_seconds: int, now: datetime | None = None
) -> bool:
    now = now or datetime.now(UTC)
    if snapshot.state == "closed":
        return True
    if snapshot.state == "half_open":
        return True
    # open
    return snapshot.opened_at is not None and now >= snapshot.opened_at + timedelta(
        seconds=cooldown_seconds
    )


def before_call(
    snapshot: BreakerSnapshot, cooldown_seconds: int, now: datetime | None = None
) -> BreakerSnapshot:
    """Call this right before attempting a call, using its return value.
    An open breaker past its cooldown transitions to half_open to admit
    exactly one trial call; everything else is unchanged."""
    now = now or datetime.now(UTC)
    if snapshot.state == "open" and should_allow_call(snapshot, cooldown_seconds, now):
        return BreakerSnapshot(
            state="half_open",
            consecutive_failures=snapshot.consecutive_failures,
            opened_at=snapshot.opened_at,
        )
    return snapshot


def record_success(snapshot: BreakerSnapshot) -> BreakerSnapshot:
    return BreakerSnapshot(state="closed", consecutive_failures=0, opened_at=None)


def record_failure(
    snapshot: BreakerSnapshot, failure_threshold: int, now: datetime | None = None
) -> BreakerSnapshot:
    now = now or datetime.now(UTC)
    failures = snapshot.consecutive_failures + 1

    if snapshot.state == "half_open":
        # the one trial call failed -- back to fully open, cooldown restarts
        return BreakerSnapshot(state="open", consecutive_failures=failures, opened_at=now)

    if failures >= failure_threshold:
        return BreakerSnapshot(state="open", consecutive_failures=failures, opened_at=now)

    return BreakerSnapshot(
        state=snapshot.state, consecutive_failures=failures, opened_at=snapshot.opened_at
    )
