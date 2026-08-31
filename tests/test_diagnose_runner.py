"""Tests for run_once(), the batch entrypoint that mirrors
src/execute/dispatcher.py's shape for the diagnosis path."""

import json
from datetime import UTC, datetime

import anthropic
import httpx2
from sqlalchemy import func, select

from src.diagnose.models import Diagnosis
from src.diagnose.runner import run_once
from src.ingest.models import Payment
from tests.conftest import make_settings

_NOW = datetime(2026, 6, 16, 14, 0, tzinfo=UTC)


def _eligible_count(session) -> int:
    """Mirrors run_once()'s own eligibility query exactly, so tests can
    assert the *delta* they caused rather than an absolute count -- this
    database also serves make run/make eval (see conftest.py's db_session
    docstring), so rows from unrelated prior activity may already be
    sitting there, eligible, before a test seeds anything of its own."""
    already_diagnosed = select(Diagnosis.order_id)
    return session.execute(
        select(func.count())
        .select_from(Payment)
        .where(Payment.status == "failed", Payment.category == "unknown")
        .where(Payment.order_id.not_in(already_diagnosed))
    ).scalar_one()


def _client_returning(payload: dict) -> anthropic.Anthropic:
    def handler(request):
        body = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        return httpx2.Response(200, json=body)

    transport = httpx2.MockTransport(handler)
    return anthropic.Anthropic(
        api_key="fake", http_client=httpx2.Client(transport=transport), max_retries=0
    )


def _client_erroring(status: int) -> anthropic.Anthropic:
    def handler(request):
        return httpx2.Response(status, json={"error": {"type": "x", "message": "simulated"}})

    transport = httpx2.MockTransport(handler)
    return anthropic.Anthropic(
        api_key="fake", http_client=httpx2.Client(transport=transport), max_retries=0
    )


def _seed_payment(
    session, order_id: str, *, status: str = "failed", category: str | None = "unknown"
) -> None:
    session.add(
        Payment(
            order_id=order_id,
            status=status,
            latest_payment_id=f"pay_{order_id}",
            amount_paise=50_000,
            currency="INR",
            method="card",
            error_reason="a_never_before_seen_error_string",
            category=category,
            raw_payload={},
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    session.flush()


_ESCALATE_PAYLOAD = {
    "category": "unknown",
    "confidence": 0.4,
    "reasoning": "not enough signal to decide responsibly",
    "cited_evidence_ids": [],
    "suggested_intervention": "escalate_to_human",
}


def test_run_once_considers_only_eligible_orders(db_session) -> None:
    baseline = _eligible_count(db_session)
    _seed_payment(db_session, "order_a")
    _seed_payment(db_session, "order_b")
    _seed_payment(db_session, "order_already_classified", category="insufficient_funds")
    _seed_payment(db_session, "order_not_failed", status="captured")

    settings = make_settings(anthropic_api_key="fake")
    summary = run_once(
        db_session, settings, limit=baseline + 2, client=_client_returning(_ESCALATE_PAYLOAD)
    )

    assert summary.considered == baseline + 2
    assert summary.succeeded == baseline + 2


def test_run_once_skips_orders_already_diagnosed(db_session) -> None:
    baseline = _eligible_count(db_session)
    _seed_payment(db_session, "order_seen_before")
    db_session.add(
        Diagnosis(
            order_id="order_seen_before",
            prompt_version="diagnose_v1",
            prompt_hash="x" * 64,
            model="claude-opus-5",
            evidence_bundle={"items": []},
            succeeded=True,
            raw_response={},
            created_at=_NOW,
        )
    )
    db_session.flush()

    settings = make_settings(anthropic_api_key="fake")
    summary = run_once(db_session, settings, client=_client_returning(_ESCALATE_PAYLOAD))

    assert summary.considered == baseline


def test_run_once_respects_the_limit(db_session) -> None:
    for i in range(3):
        _seed_payment(db_session, f"order_limit_{i}")

    settings = make_settings(anthropic_api_key="fake")
    summary = run_once(db_session, settings, limit=2, client=_client_returning(_ESCALATE_PAYLOAD))

    assert summary.considered == 2


def test_run_once_tracks_failures_by_reason(db_session) -> None:
    baseline = _eligible_count(db_session)
    _seed_payment(db_session, "order_will_fail_1")
    _seed_payment(db_session, "order_will_fail_2")

    settings = make_settings(anthropic_api_key="fake")
    summary = run_once(db_session, settings, client=_client_erroring(500))

    assert summary.considered == baseline + 2
    assert summary.failed == baseline + 2
    assert summary.succeeded == 0
    assert summary.failure_reasons == {"api_error_500": baseline + 2}
