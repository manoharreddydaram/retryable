"""Builds the evidence bundle for one long-tail diagnosis: this payment's
own signals, plus recent related history queried from data this project
already keeps. This is a raw count, not a statistically tested anomaly --
that determination belongs to Stage 8's degradation detector, where it
exists; here it's just the same context a human analyst would want to see
before guessing at a cause.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingest.models import Payment
from src.ingest.schemas import RazorpayPaymentEntity

_LOOKBACK = timedelta(hours=24)


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    description: str


@dataclass(frozen=True)
class EvidenceBundle:
    items: list[EvidenceItem] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join(f"[{item.id}] {item.description}" for item in self.items)

    def valid_ids(self) -> set[str]:
        return {item.id for item in self.items}


def build_evidence_bundle(
    session: Session, payment_entity: RazorpayPaymentEntity, now: datetime
) -> EvidenceBundle:
    raw_reason = (
        payment_entity.error_reason or payment_entity.error_code or "(no error text provided)"
    )
    items = [
        EvidenceItem("E1", f"This payment's raw error text: '{raw_reason}'"),
        EvidenceItem("E2", f"Payment method: {payment_entity.method or 'unknown'}"),
        EvidenceItem("E3", f"Amount: Rs {payment_entity.amount / 100:,.2f}"),
        EvidenceItem("E4", f"Time of attempt (UTC): {now.strftime('%A %H:%M')}"),
    ]

    window_start = now - _LOOKBACK

    if payment_entity.error_reason:
        similar_count = session.execute(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.error_reason == payment_entity.error_reason,
                Payment.status == "failed",
                Payment.updated_at >= window_start,
            )
        ).scalar_one()
        items.append(
            EvidenceItem(
                "E5",
                f"{similar_count} other order(s) show this exact error text, still failed, "
                "in the last 24 hours (a raw count, not a statistically confirmed trend).",
            )
        )

    total_recent_failures = session.execute(
        select(func.count())
        .select_from(Payment)
        .where(Payment.status == "failed", Payment.updated_at >= window_start)
    ).scalar_one()
    items.append(
        EvidenceItem(
            "E6",
            f"{total_recent_failures} total failed order(s) across all reasons "
            "in the last 24 hours.",
        )
    )

    return EvidenceBundle(items=items)
