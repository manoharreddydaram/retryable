"""Orchestrates one webhook delivery end to end: claim, decide, classify,
persist, decide again (policy), enqueue, record.

The order_id is fully serialised with a Postgres advisory lock before its
current status is read. Razorpay's own retry policy (resend on anything
that isn't a 2xx within 5 seconds, for up to 24 hours) makes near-concurrent
redelivery for the same order a real possibility, not a hypothetical, so two
events racing each other into an inconsistent status is a real bug class to
close, not a theoretical one.

Event dedup is a single atomic INSERT ... ON CONFLICT DO NOTHING: whichever
request claims the event_id first proceeds, the other is told it lost the
race and stops immediately without touching payment state twice.

Every payment.failed that is actually applied gets run through the Stage 3
deterministic classifier, then Stage 4's policy engine, which authorises at
most one intervention. If that intervention calls Razorpay, an outbox entry
is written in the *same transaction* as the Decision -- see
src/execute/outbox.py -- so the decision and the intent to act on it can
never diverge.

skip_policy=True processes classification and payment state normally but
never invokes the policy engine -- used by Stage 6's eval harness to build
its control arm, which needs the same real payment/classification records
as treatment but a deliberately naive decision instead of a real one.

now defaults to the real current time for live traffic, but Stage 6's eval
harness passes each synthetic failure's own occurred_at explicitly. This
matters for two reasons, not one: it keeps the quiet-hours gate from
depending on what time of day you happen to run `make eval` (a batch run
must be reproducible regardless of wall-clock time), and it keeps treatment
and control's outbox entries on the same synthetic timeline so neither arm
is dispatched first merely because it happened to be enqueued using a
different clock.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.classify.rules import ClassificationResult, classify
from src.config import Settings, get_settings
from src.execute.outbox import enqueue_if_needed
from src.ingest.models import Payment, WebhookEvent
from src.ingest.schemas import RazorpayPaymentEntity, RazorpayWebhookEnvelope
from src.ingest.state_machine import PaymentStatus, decide_transition
from src.ledger.writer import append_entry
from src.policy.context import touches_in_window
from src.policy.engine import DecisionInput, Proposal, decide
from src.policy.models import Decision
from src.policy.rules_table import propose_default

_SUPPORTED_EVENTS: dict[str, PaymentStatus] = {
    "payment.failed": PaymentStatus.FAILED,
    "payment.captured": PaymentStatus.CAPTURED,
}


@dataclass(frozen=True)
class IngestResult:
    outcome: str
    order_id: str | None
    category: str | None = None
    authorized_intervention: str | None = None


def ingest_webhook(
    session: Session,
    *,
    event_id: str,
    raw_body: dict,
    settings: Settings | None = None,
    skip_policy: bool = False,
    now: datetime | None = None,
) -> IngestResult:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)

    envelope = RazorpayWebhookEnvelope.model_validate(raw_body)
    incoming_status = _SUPPORTED_EVENTS.get(envelope.event)
    payment_entity = envelope.payment_entity() if incoming_status else None

    subject_id: str | None = None
    payment_id: str | None = None
    reason: str | None = None
    classification: ClassificationResult | None = None

    if incoming_status is None or payment_entity is None:
        outcome = "ignored_unsupported_event"
    else:
        subject_id = payment_entity.order_id or payment_entity.id
        payment_id = payment_entity.id
        _lock_subject(session, subject_id)
        current = _load_current_status(session, subject_id)
        decision = decide_transition(current, incoming_status)
        reason = decision.reason
        if not decision.allowed:
            outcome = "rejected_backward_transition"
        elif current == PaymentStatus.FAILED and incoming_status == PaymentStatus.CAPTURED:
            outcome = "recovered"
        else:
            outcome = "applied"

        if incoming_status == PaymentStatus.FAILED and outcome != "rejected_backward_transition":
            classification = classify(payment_entity.error_reason, payment_entity.error_code)

    claimed = _claim_event(
        session, event_id, envelope.event, payment_id, subject_id, outcome, raw_body
    )
    if not claimed:
        existing = session.get(WebhookEvent, event_id)
        existing_order_id = existing.order_id if existing else None
        _append_ledger(
            session, existing_order_id or "unknown", envelope.event, "duplicate_ignored", raw_body
        )
        return IngestResult(outcome="duplicate_ignored", order_id=existing_order_id)

    if (
        incoming_status is not None
        and payment_entity is not None
        and outcome in ("applied", "recovered")
    ):
        _upsert_payment(
            session, subject_id, incoming_status, payment_entity, raw_body, classification
        )

    authorized_intervention = None
    if classification is not None and outcome == "applied" and not skip_policy:
        authorized_intervention = _decide_and_enqueue(
            session, subject_id, payment_entity, classification, settings, now
        )

    ledger_extra = None
    if classification is not None:
        ledger_extra = {
            "category": classification.category.value,
            "recoverable": classification.profile.recoverable,
        }

    _append_ledger(
        session,
        subject_id or "unknown",
        envelope.event,
        outcome,
        raw_body,
        reason=reason if outcome == "rejected_backward_transition" else None,
        extra=ledger_extra,
    )
    return IngestResult(
        outcome=outcome,
        order_id=subject_id,
        category=classification.category.value if classification else None,
        authorized_intervention=authorized_intervention,
    )


def _decide_and_enqueue(
    session: Session,
    subject_id: str,
    payment_entity: RazorpayPaymentEntity,
    classification: ClassificationResult,
    settings: Settings,
    now: datetime,
) -> str:
    proposal = Proposal(
        intervention=propose_default(classification.category).value, source="category_rules"
    )
    ctx = DecisionInput(
        category=classification.category,
        profile=classification.profile,
        confidence=classification.confidence,
        amount_paise=payment_entity.amount,
        touches_in_window=touches_in_window(session, payment_entity.contact, now=now),
        # live traffic has no batch context; Stage 6 supplies a real count
        interventions_dispatched_in_batch=0,
        now=now,
    )
    outcome = decide(proposal, ctx, settings)

    row = Decision(
        order_id=subject_id,
        payer_contact=payment_entity.contact,
        category=classification.category.value,
        confidence=ctx.confidence,
        amount_paise=payment_entity.amount,
        proposed_intervention=outcome.proposed_intervention,
        authorized_intervention=outcome.authorized_intervention.value,
        overridden=outcome.overridden,
        rule_id=outcome.rule_id,
        reason=outcome.reason,
        retry_at=outcome.retry_at,
        decided_at=now,
    )
    session.add(row)
    session.flush()  # populate row.id before it's referenced by the outbox entry

    enqueue_if_needed(session, row)

    append_entry(
        session,
        entity_type="decision",
        entity_id=str(row.id),
        event_type=f"decision.{outcome.rule_id.lower()}",
        actor="system:policy",
        payload={
            "order_id": subject_id,
            "category": classification.category.value,
            "confidence": classification.confidence,
            "proposed": outcome.proposed_intervention,
            "authorized": outcome.authorized_intervention.value,
            "overridden": outcome.overridden,
            "rule_id": outcome.rule_id,
            "reason": outcome.reason,
        },
    )
    return outcome.authorized_intervention.value


def _lock_subject(session: Session, subject_id: str) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"retryable.payment.{subject_id}"},
    )


def _load_current_status(session: Session, subject_id: str) -> PaymentStatus | None:
    status = session.execute(
        select(Payment.status).where(Payment.order_id == subject_id).with_for_update()
    ).scalar_one_or_none()
    return PaymentStatus(status) if status else None


def _claim_event(
    session: Session,
    event_id: str,
    event_type: str,
    payment_id: str | None,
    order_id: str | None,
    outcome: str,
    raw_body: dict,
) -> bool:
    stmt = (
        pg_insert(WebhookEvent)
        .values(
            event_id=event_id,
            event_type=event_type,
            payment_id=payment_id,
            order_id=order_id,
            outcome=outcome,
            raw_payload=raw_body,
            received_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(WebhookEvent.event_id)
    )
    return session.execute(stmt).scalar_one_or_none() is not None


def _upsert_payment(
    session: Session,
    subject_id: str,
    incoming_status: PaymentStatus,
    payment_entity: RazorpayPaymentEntity,
    raw_body: dict,
    classification: ClassificationResult | None,
) -> None:
    now = datetime.now(UTC)
    existing = session.get(Payment, subject_id)

    error_code = payment_entity.error_code if classification else None
    error_reason = payment_entity.error_reason if classification else None
    category = classification.category.value if classification else None

    if existing is None:
        session.add(
            Payment(
                order_id=subject_id,
                status=incoming_status.value,
                latest_payment_id=payment_entity.id,
                amount_paise=payment_entity.amount,
                currency=payment_entity.currency,
                method=payment_entity.method,
                error_code=error_code,
                error_reason=error_reason,
                category=category,
                raw_payload=raw_body,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        existing.status = incoming_status.value
        existing.latest_payment_id = payment_entity.id
        existing.amount_paise = payment_entity.amount
        existing.method = payment_entity.method
        if classification is not None:
            existing.error_code = error_code
            existing.error_reason = error_reason
            existing.category = category
        existing.raw_payload = raw_body
        existing.updated_at = now


def _append_ledger(
    session: Session,
    subject_id: str,
    razorpay_event: str,
    outcome: str,
    raw_body: dict,
    reason: str | None = None,
    extra: dict | None = None,
) -> None:
    payload = {"razorpay_event": razorpay_event, "outcome": outcome, "raw_webhook": raw_body}
    if reason:
        payload["reason"] = reason
    if extra:
        payload.update(extra)
    append_entry(
        session,
        entity_type="payment",
        entity_id=subject_id,
        event_type=f"webhook.{outcome}",
        actor="system:ingest",
        payload=payload,
    )
