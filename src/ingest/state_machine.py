"""The forward-only transition rule, kept deliberately separate from I/O.

A single Razorpay payment_id never legitimately changes status once
Razorpay reports it as failed or captured. What *does* change is whether the
order behind it is still open: a failed attempt followed by a captured
attempt on the same order is a real recovery, and must be allowed. A
captured order followed by a failed attempt is not a real reversal -- it's
a stale or out-of-order delivery -- and must be rejected. This function
knows only that rule; it has no idea what a webhook or a database is.
"""

from dataclasses import dataclass
from enum import StrEnum


class PaymentStatus(StrEnum):
    FAILED = "failed"
    CAPTURED = "captured"


_ALLOWED: dict[PaymentStatus, set[PaymentStatus]] = {
    PaymentStatus.FAILED: {PaymentStatus.FAILED, PaymentStatus.CAPTURED},
    PaymentStatus.CAPTURED: {PaymentStatus.CAPTURED},
}


@dataclass(frozen=True)
class TransitionDecision:
    allowed: bool
    changed: bool
    reason: str


def decide_transition(current: PaymentStatus | None, incoming: PaymentStatus) -> TransitionDecision:
    if current is None:
        return TransitionDecision(allowed=True, changed=True, reason="new order")

    if incoming in _ALLOWED[current]:
        return TransitionDecision(
            allowed=True, changed=incoming != current, reason=f"{current} -> {incoming}"
        )

    return TransitionDecision(
        allowed=False,
        changed=False,
        reason=f"rejected: {current} -> {incoming} is not a forward transition",
    )
