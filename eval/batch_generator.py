"""Generates a batch of synthetic failed payments with a realistic category
mix.

The composition below is anchored, where a citation actually applies, to
Baremetrics' 2026 dunning benchmark: "roughly half are insufficient-funds
(soft) declines, a quarter to a third are risk-management hard flags, and
10-15% are card issues." Those three figures are scaled down (not taken at
face value) to make room for categories that citation doesn't cover at all
-- it describes card-decline composition specifically, not the full range
of failure causes this project's taxonomy handles (abandonment, technical
outages, merchant-side config errors, and the genuine unknown long tail).
The remaining categories are this project's own reasoned estimate, stated
as such. See EVALUATION.md's "known limitations": this is an estimate of a
mid-market merchant's failure profile, not an observed distribution.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# category -> (weight, a real error_reason representative of that category)
# "unknown" deliberately uses a string that is NOT in error_taxonomy.yaml,
# to genuinely exercise novel-string handling rather than assume it.
_CATEGORY_MIX: list[tuple[str, float, str]] = [
    ("insufficient_funds", 0.30, "insufficient_funds"),
    ("issuer_declined", 0.18, "card_declined"),
    ("instrument_blocked", 0.08, "card_expired"),
    ("auth_abandoned", 0.15, "payment_cancelled"),
    ("input_error_retriable", 0.12, "incorrect_cvv"),
    ("infra_outage", 0.05, "bank_not_available"),
    ("ambiguous_verify_before_acting", 0.05, "payment_timed_out"),
    ("merchant_config_error", 0.03, "invalid_order_id"),
    ("unknown", 0.04, "acquirer_response_code_9f_37_unmapped"),
]

_METHODS = ["card", "upi", "netbanking"]

# A fixed reference instant, independent of when this script actually runs,
# so every time-of-day-sensitive outcome (the quiet-hours gate, above all)
# is exactly reproducible given the same seed -- not dependent on what real
# hour you happened to invoke `make eval` at. Occurrences are spread across
# a 72-hour window from this epoch so the batch realistically covers both
# inside and outside quiet hours, rather than clustering at a single
# instant that might duck the gate entirely by accident.
_SYNTHETIC_EPOCH = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_SPREAD_HOURS = 72


@dataclass(frozen=True)
class SyntheticFailure:
    order_id: str
    payment_id: str
    payer_contact: str
    amount_paise: int
    method: str
    error_reason: str
    true_category: str  # known by construction, used only for grading classifier accuracy
    occurred_at: datetime

    def to_webhook_envelope(self) -> dict:
        return {
            "entity": "event",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": self.payment_id,
                        "amount": self.amount_paise,
                        "currency": "INR",
                        "status": "failed",
                        "order_id": self.order_id,
                        "method": self.method,
                        "contact": self.payer_contact,
                        "error_reason": self.error_reason,
                        "error_code": "BAD_REQUEST_ERROR",
                    }
                }
            },
            "created_at": int(self.occurred_at.timestamp()),
        }


def generate_batch(size: int, seed: int, repeat_payer_rate: float = 0.15) -> list[SyntheticFailure]:
    """repeat_payer_rate controls how often a new failure is assigned to a
    payer already used earlier in this same batch -- needed to exercise the
    touch cap at all, since a batch of all-unique payers never would."""
    rng = random.Random(seed)

    categories = [c for c, _, _ in _CATEGORY_MIX]
    weights = [w for _, w, _ in _CATEGORY_MIX]
    reason_by_category = {c: r for c, _, r in _CATEGORY_MIX}

    payer_pool: list[str] = []
    batch: list[SyntheticFailure] = []

    for i in range(size):
        if payer_pool and rng.random() < repeat_payer_rate:
            payer_contact = rng.choice(payer_pool)
        else:
            payer_contact = f"+9198{rng.randint(10_000_000, 99_999_999)}"
            payer_pool.append(payer_contact)

        category = rng.choices(categories, weights=weights, k=1)[0]
        raw_amount = int(rng.lognormvariate(mu=7.5, sigma=0.9))
        amount_paise = max(
            9_900, min(raw_amount, 1_500_000)
        )  # clamp to a plausible Rs.99-Rs.15,000 band
        occurred_at = _SYNTHETIC_EPOCH + timedelta(hours=rng.uniform(0, _SPREAD_HOURS))

        batch.append(
            SyntheticFailure(
                order_id=f"eval_order_{seed}_{i:04d}",
                payment_id=f"eval_pay_{seed}_{i:04d}",
                payer_contact=payer_contact,
                amount_paise=amount_paise,
                method=rng.choice(_METHODS),
                error_reason=reason_by_category[category],
                true_category=category,
                occurred_at=occurred_at,
            )
        )
    return batch


def split_arms(
    batch: list[SyntheticFailure], seed: int, treatment_share: float = 0.7
) -> tuple[list[SyntheticFailure], list[SyntheticFailure]]:
    rng = random.Random(f"{seed}-arm-split")  # distinct stream from category/amount assignment
    shuffled = batch.copy()
    rng.shuffle(shuffled)
    split_point = int(len(shuffled) * treatment_share)
    return shuffled[:split_point], shuffled[split_point:]
