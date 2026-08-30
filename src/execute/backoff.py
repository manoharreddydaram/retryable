"""Exponential backoff with jitter for outbox retry scheduling.

Jitter exists so that if many entries fail at once (a real outage, not a
one-off), their retries don't all land on Razorpay in the same instant and
look like a second, self-inflicted spike on top of the first failure.
"""

import random
from datetime import UTC, datetime, timedelta


def compute_delay_seconds(
    attempts: int,
    base_seconds: float = 2.0,
    max_seconds: float = 300.0,
    jitter_ratio: float = 0.2,
) -> float:
    """attempts=1 is the delay before the *second* try. Grows 2^(attempts-1)
    times base_seconds, capped at max_seconds, then jittered by +/- jitter_ratio."""
    raw = min(base_seconds * (2 ** max(attempts - 1, 0)), max_seconds)
    jitter = raw * jitter_ratio
    return raw + random.uniform(-jitter, jitter)


def next_attempt_at(
    attempts: int,
    now: datetime | None = None,
    base_seconds: float = 2.0,
    max_seconds: float = 300.0,
) -> datetime:
    now = now or datetime.now(UTC)
    return now + timedelta(seconds=compute_delay_seconds(attempts, base_seconds, max_seconds))
