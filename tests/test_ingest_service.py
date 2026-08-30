"""Ingest service tests against a real Postgres instance (see conftest.py).

Proves the actual designed failure from the README: a late payment.captured
for an order already considered failed must recover it, and a late
payment.failed for an already-captured order must be rejected. Proven again
at the HTTP layer in test_webhook_endpoint.py.
"""

from sqlalchemy import select

from src.execute.models import OutboxEntry
from src.ingest.models import Payment, WebhookEvent
from src.ingest.service import ingest_webhook
from src.policy.models import Decision
from tests.conftest import make_settings


def _envelope(
    event: str,
    payment_id: str,
    order_id: str,
    status: str,
    amount: int = 50000,
    error_reason: str | None = None,
    contact: str | None = None,
) -> dict:
    entity = {
        "id": payment_id,
        "amount": amount,
        "currency": "INR",
        "status": status,
        "order_id": order_id,
        "method": "card",
    }
    if error_reason:
        entity["error_reason"] = error_reason
        entity["error_code"] = "BAD_REQUEST_ERROR"
    if contact:
        entity["contact"] = contact
    return {
        "entity": "event",
        "event": event,
        "contains": ["payment"],
        "payload": {"payment": {"entity": entity}},
        "created_at": 1700000000,
    }


def test_new_failed_payment_creates_a_payment_row(db_session) -> None:
    result = ingest_webhook(
        db_session,
        event_id="evt_1",
        raw_body=_envelope("payment.failed", "pay_1", "order_1", "failed"),
    )
    assert result.outcome == "applied"

    payment = db_session.get(Payment, "order_1")
    assert payment.status == "failed"
    assert payment.latest_payment_id == "pay_1"


def test_duplicate_event_id_is_ignored(db_session) -> None:
    body = _envelope("payment.failed", "pay_1", "order_1", "failed")
    first = ingest_webhook(db_session, event_id="evt_1", raw_body=body)
    second = ingest_webhook(db_session, event_id="evt_1", raw_body=body)

    assert first.outcome == "applied"
    assert second.outcome == "duplicate_ignored"

    rows = (
        db_session.execute(select(WebhookEvent).where(WebhookEvent.event_id == "evt_1"))
        .scalars()
        .all()
    )
    assert len(rows) == 1


def test_late_captured_recovers_a_failed_order(db_session) -> None:
    ingest_webhook(
        db_session,
        event_id="evt_1",
        raw_body=_envelope("payment.failed", "pay_1", "order_1", "failed"),
    )
    result = ingest_webhook(
        db_session,
        event_id="evt_2",
        raw_body=_envelope("payment.captured", "pay_2", "order_1", "captured"),
    )

    assert result.outcome == "recovered"
    payment = db_session.get(Payment, "order_1")
    assert payment.status == "captured"
    assert payment.latest_payment_id == "pay_2"


def test_late_failed_after_captured_is_rejected(db_session) -> None:
    ingest_webhook(
        db_session,
        event_id="evt_1",
        raw_body=_envelope("payment.captured", "pay_1", "order_2", "captured"),
    )
    result = ingest_webhook(
        db_session,
        event_id="evt_2",
        raw_body=_envelope("payment.failed", "pay_2", "order_2", "failed"),
    )

    assert result.outcome == "rejected_backward_transition"
    payment = db_session.get(Payment, "order_2")
    assert payment.status == "captured"
    assert payment.latest_payment_id == "pay_1"


def test_unsupported_event_type_is_ignored_without_error(db_session) -> None:
    body = {"entity": "event", "event": "refund.processed", "payload": {}}
    result = ingest_webhook(db_session, event_id="evt_1", raw_body=body)
    assert result.outcome == "ignored_unsupported_event"


def test_failed_payment_is_classified_and_stored(db_session) -> None:
    body = _envelope(
        "payment.failed", "pay_1", "order_1", "failed", error_reason="insufficient_funds"
    )
    result = ingest_webhook(db_session, event_id="evt_1", raw_body=body)

    assert result.category == "insufficient_funds"
    payment = db_session.get(Payment, "order_1")
    assert payment.category == "insufficient_funds"
    assert payment.error_reason == "insufficient_funds"


def test_unrecognized_error_reason_classifies_as_unknown(db_session) -> None:
    body = _envelope(
        "payment.failed", "pay_1", "order_1", "failed", error_reason="a_reason_never_documented"
    )
    result = ingest_webhook(db_session, event_id="evt_1", raw_body=body)

    assert result.category == "unknown"


def test_recovery_preserves_the_original_failure_category(db_session) -> None:
    ingest_webhook(
        db_session,
        event_id="evt_1",
        raw_body=_envelope(
            "payment.failed", "pay_1", "order_1", "failed", error_reason="card_declined"
        ),
    )
    ingest_webhook(
        db_session,
        event_id="evt_2",
        raw_body=_envelope("payment.captured", "pay_2", "order_1", "captured"),
    )

    payment = db_session.get(Payment, "order_1")
    assert payment.status == "captured"
    assert payment.error_reason == "card_declined"
    assert payment.category == "issuer_declined"


def test_recoverable_failure_creates_a_decision_and_an_outbox_entry(db_session) -> None:
    body = _envelope("payment.failed", "pay_1", "order_1", "failed", error_reason="incorrect_cvv")
    result = ingest_webhook(db_session, event_id="evt_1", raw_body=body, settings=make_settings())

    assert result.authorized_intervention == "send_payment_link"

    decision = db_session.execute(
        select(Decision).where(Decision.order_id == "order_1")
    ).scalar_one()
    assert decision.category == "input_error_retriable"
    assert decision.overridden is False
    assert decision.rule_id == "PROPOSAL_AUTHORIZED"

    entry = db_session.execute(
        select(OutboxEntry).where(OutboxEntry.decision_id == decision.id)
    ).scalar_one()
    assert entry.status == "pending"
    assert entry.idempotency_key.startswith("rtx-")


def test_unrecoverable_failure_creates_a_decision_but_no_outbox_entry(db_session) -> None:
    body = _envelope("payment.failed", "pay_1", "order_2", "failed", error_reason="card_expired")
    result = ingest_webhook(db_session, event_id="evt_1", raw_body=body, settings=make_settings())

    assert result.authorized_intervention == "suppress"

    decision = db_session.execute(
        select(Decision).where(Decision.order_id == "order_2")
    ).scalar_one()
    assert decision.overridden is True
    assert decision.rule_id == "UNRECOVERABLE_CATEGORY"

    rows = (
        db_session.execute(select(OutboxEntry).where(OutboxEntry.decision_id == decision.id))
        .scalars()
        .all()
    )
    assert rows == []


def test_touch_cap_is_enforced_against_real_prior_outreach(db_session) -> None:
    payer_contact = "+911234567890"
    settings = make_settings(max_touches_per_payer_7d=1)

    # A real prior failure that resulted in a real (successfully dispatched) outreach.
    prior_body = _envelope(
        "payment.failed",
        "pay_prior",
        "order_prior",
        "failed",
        error_reason="incorrect_cvv",
        contact=payer_contact,
    )
    ingest_webhook(db_session, event_id="evt_prior", raw_body=prior_body, settings=settings)

    prior_decision = db_session.execute(
        select(Decision).where(Decision.order_id == "order_prior")
    ).scalar_one()
    prior_entry = db_session.execute(
        select(OutboxEntry).where(OutboxEntry.decision_id == prior_decision.id)
    ).scalar_one()
    prior_entry.status = "complete"  # simulate the dispatcher having already sent this successfully
    db_session.flush()

    # A new, different failure for the same payer.
    new_body = _envelope(
        "payment.failed",
        "pay_new",
        "order_new",
        "failed",
        error_reason="incorrect_cvv",
        contact=payer_contact,
    )
    result = ingest_webhook(db_session, event_id="evt_new", raw_body=new_body, settings=settings)

    assert result.authorized_intervention == "suppress"
    new_decision = db_session.execute(
        select(Decision).where(Decision.order_id == "order_new")
    ).scalar_one()
    assert new_decision.rule_id == "TOUCH_CAP_EXCEEDED"
