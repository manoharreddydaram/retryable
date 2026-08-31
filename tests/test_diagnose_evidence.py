"""Evidence bundle tests against a real Postgres instance (see conftest.py)."""

from datetime import UTC, datetime, timedelta

from src.diagnose.evidence import EvidenceBundle, EvidenceItem, build_evidence_bundle
from src.ingest.models import Payment
from src.ingest.schemas import RazorpayPaymentEntity


def _seed_payment(
    session, order_id: str, error_reason: str, now: datetime, hours_ago: float
) -> None:
    when = now - timedelta(hours=hours_ago)
    session.add(
        Payment(
            order_id=order_id,
            status="failed",
            latest_payment_id=f"pay_{order_id}",
            amount_paise=10_000,
            currency="INR",
            method="card",
            error_reason=error_reason,
            category="unknown",
            raw_payload={},
            created_at=when,
            updated_at=when,
        )
    )
    session.flush()


def test_bundle_includes_the_payments_own_signals(db_session) -> None:
    now = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
    entity = RazorpayPaymentEntity(
        id="pay_1",
        amount=50_000,
        status="failed",
        order_id="order_1",
        method="upi",
        error_reason="some_never_before_seen_string",
    )
    rendered = build_evidence_bundle(db_session, entity, now).render()

    assert "some_never_before_seen_string" in rendered
    assert "upi" in rendered
    assert "500.00" in rendered  # Rs 500.00 for 50,000 paise
    assert "Monday 14:00" in rendered


def test_bundle_counts_recent_similar_failures(db_session) -> None:
    now = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
    _seed_payment(db_session, "order_similar_1", "weird_new_error", now, hours_ago=2)
    _seed_payment(db_session, "order_similar_2", "weird_new_error", now, hours_ago=5)
    _seed_payment(db_session, "order_different", "some_other_error", now, hours_ago=1)

    entity = RazorpayPaymentEntity(
        id="pay_x",
        amount=10_000,
        status="failed",
        order_id="order_x",
        method="card",
        error_reason="weird_new_error",
    )
    rendered = build_evidence_bundle(db_session, entity, now).render()

    assert "2 other order(s)" in rendered


def test_bundle_excludes_failures_outside_the_24h_window(db_session) -> None:
    now = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
    _seed_payment(db_session, "order_old", "weird_new_error", now, hours_ago=48)

    entity = RazorpayPaymentEntity(
        id="pay_x",
        amount=10_000,
        status="failed",
        order_id="order_x",
        method="card",
        error_reason="weird_new_error",
    )
    rendered = build_evidence_bundle(db_session, entity, now).render()

    assert "0 other order(s)" in rendered


def test_evidence_bundle_valid_ids() -> None:
    bundle = EvidenceBundle(items=[EvidenceItem("E1", "a"), EvidenceItem("E2", "b")])
    assert bundle.valid_ids() == {"E1", "E2"}
