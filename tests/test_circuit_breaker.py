"""Pure tests for the three-state circuit breaker. No database."""

from datetime import UTC, datetime, timedelta

from src.execute.circuit_breaker import (
    BreakerSnapshot,
    before_call,
    record_failure,
    record_success,
    should_allow_call,
)

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_CLOSED = BreakerSnapshot(state="closed", consecutive_failures=0, opened_at=None)


def test_closed_breaker_allows_calls() -> None:
    assert should_allow_call(_CLOSED, cooldown_seconds=60, now=_NOW) is True


def test_failures_below_threshold_stay_closed() -> None:
    snapshot = _CLOSED
    for _ in range(4):
        snapshot = record_failure(snapshot, failure_threshold=5, now=_NOW)
    assert snapshot.state == "closed"


def test_failures_reaching_threshold_opens_the_breaker() -> None:
    snapshot = _CLOSED
    for _ in range(5):
        snapshot = record_failure(snapshot, failure_threshold=5, now=_NOW)
    assert snapshot.state == "open"
    assert snapshot.opened_at == _NOW


def test_open_breaker_refuses_calls_before_cooldown() -> None:
    snapshot = BreakerSnapshot(state="open", consecutive_failures=5, opened_at=_NOW)
    soon = _NOW + timedelta(seconds=10)
    assert should_allow_call(snapshot, cooldown_seconds=60, now=soon) is False


def test_open_breaker_allows_a_call_after_cooldown() -> None:
    snapshot = BreakerSnapshot(state="open", consecutive_failures=5, opened_at=_NOW)
    later = _NOW + timedelta(seconds=61)
    assert should_allow_call(snapshot, cooldown_seconds=60, now=later) is True


def test_before_call_transitions_expired_open_breaker_to_half_open() -> None:
    snapshot = BreakerSnapshot(state="open", consecutive_failures=5, opened_at=_NOW)
    later = _NOW + timedelta(seconds=61)
    assert before_call(snapshot, cooldown_seconds=60, now=later).state == "half_open"


def test_before_call_leaves_a_closed_breaker_unchanged() -> None:
    assert before_call(_CLOSED, cooldown_seconds=60, now=_NOW) == _CLOSED


def test_successful_half_open_trial_closes_the_breaker() -> None:
    half_open = BreakerSnapshot(state="half_open", consecutive_failures=5, opened_at=_NOW)
    closed = record_success(half_open)
    assert closed.state == "closed"
    assert closed.consecutive_failures == 0


def test_failed_half_open_trial_reopens_the_breaker() -> None:
    half_open = BreakerSnapshot(state="half_open", consecutive_failures=5, opened_at=_NOW)
    later = _NOW + timedelta(seconds=5)
    reopened = record_failure(half_open, failure_threshold=5, now=later)
    assert reopened.state == "open"
    assert reopened.opened_at == later


def test_success_resets_failure_count_even_when_closed() -> None:
    snapshot = BreakerSnapshot(state="closed", consecutive_failures=3, opened_at=None)
    assert record_success(snapshot).consecutive_failures == 0
