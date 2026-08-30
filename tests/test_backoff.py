"""Pure tests for exponential backoff with jitter. No database."""

from datetime import UTC, datetime

from src.execute.backoff import compute_delay_seconds, next_attempt_at


def test_delay_grows_with_attempts() -> None:
    small = compute_delay_seconds(1, jitter_ratio=0.0)
    large = compute_delay_seconds(4, jitter_ratio=0.0)
    assert large > small


def test_delay_is_capped_at_max_seconds() -> None:
    delay = compute_delay_seconds(50, base_seconds=2.0, max_seconds=300.0, jitter_ratio=0.0)
    assert delay == 300.0


def test_jitter_stays_within_the_configured_ratio() -> None:
    # attempts=3 -> raw = base * 2^(3-1) = 10.0 * 4 = 40.0, jittered by +/-20%
    for _ in range(50):
        delay = compute_delay_seconds(3, base_seconds=10.0, max_seconds=1000.0, jitter_ratio=0.2)
        assert 32.0 <= delay <= 48.0


def test_first_attempt_delay_equals_base_with_no_jitter() -> None:
    assert compute_delay_seconds(1, base_seconds=2.0, jitter_ratio=0.0) == 2.0


def test_next_attempt_at_is_in_the_future() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    scheduled = next_attempt_at(1, now=now, base_seconds=5.0)
    assert scheduled > now
