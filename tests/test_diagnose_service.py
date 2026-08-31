"""Tests for diagnose_and_decide(), the Stage 7 orchestrator. Uses a real
Postgres session (see conftest.py) and a mocked Anthropic transport so no
network call or real credential is ever needed.
"""

import json
from datetime import UTC, datetime

import anthropic
import httpx2
from sqlalchemy import select

from src.diagnose.models import Diagnosis
from src.diagnose.service import diagnose_and_decide
from src.execute.models import OutboxEntry
from src.ingest.models import Payment
from src.policy.models import Decision
from tests.conftest import make_settings

# A Tuesday, 14:00 UTC -- outside the default 21:00-09:00 quiet-hours window,
# so a send_payment_link proposal isn't deferred to WAIT for a reason this
# test doesn't care about.
_NOW = datetime(2026, 6, 16, 14, 0, tzinfo=UTC)


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
    session,
    order_id: str,
    *,
    status: str = "failed",
    category: str | None = "unknown",
    contact=None,
    amount_paise: int = 50_000,
) -> Payment:
    payment = Payment(
        order_id=order_id,
        status=status,
        latest_payment_id=f"pay_{order_id}",
        amount_paise=amount_paise,
        currency="INR",
        method="card",
        payer_contact=contact,
        error_reason="a_never_before_seen_error_string",
        category=category,
        raw_payload={},
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(payment)
    session.flush()
    return payment


def test_missing_payment_is_not_eligible(db_session) -> None:
    settings = make_settings(anthropic_api_key="fake")
    result = diagnose_and_decide(db_session, "order_does_not_exist", settings, now=_NOW)
    assert result.attempted is False
    assert result.reason == "not_eligible"


def test_already_classified_payment_is_not_eligible(db_session) -> None:
    _seed_payment(db_session, "order_classified", category="insufficient_funds")
    settings = make_settings(anthropic_api_key="fake")
    result = diagnose_and_decide(db_session, "order_classified", settings, now=_NOW)
    assert result.attempted is False
    assert result.reason == "not_eligible"


def test_non_failed_payment_is_not_eligible(db_session) -> None:
    _seed_payment(db_session, "order_captured", status="captured")
    settings = make_settings(anthropic_api_key="fake")
    result = diagnose_and_decide(db_session, "order_captured", settings, now=_NOW)
    assert result.attempted is False
    assert result.reason == "not_eligible"


def test_order_already_diagnosed_is_skipped(db_session) -> None:
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
    result = diagnose_and_decide(db_session, "order_seen_before", settings, now=_NOW)
    assert result.attempted is False
    assert result.reason == "already_diagnosed"


def test_llm_failure_is_recorded_and_degrades_gracefully(db_session) -> None:
    _seed_payment(db_session, "order_llm_down")
    settings = make_settings(anthropic_api_key="fake")

    result = diagnose_and_decide(
        db_session, "order_llm_down", settings, now=_NOW, client=_client_erroring(500)
    )

    assert result.attempted is True
    assert result.succeeded is False
    assert result.upgraded is False
    assert result.reason == "api_error_500"

    row = db_session.execute(
        select(Diagnosis).where(Diagnosis.order_id == "order_llm_down")
    ).scalar_one()
    assert row.succeeded is False
    assert row.failure_reason == "api_error_500"

    assert (
        db_session.execute(select(Decision).where(Decision.order_id == "order_llm_down")).first()
        is None
    )


def test_below_confidence_floor_persists_diagnosis_but_makes_no_decision(db_session) -> None:
    _seed_payment(db_session, "order_low_confidence")
    settings = make_settings(anthropic_api_key="fake", min_diagnosis_confidence=0.7)
    client = _client_returning(
        {
            "category": "unknown",
            "confidence": 0.3,
            "reasoning": "too little evidence to decide responsibly",
            "cited_evidence_ids": [],
            "suggested_intervention": "escalate_to_human",
        }
    )

    result = diagnose_and_decide(
        db_session, "order_low_confidence", settings, now=_NOW, client=client
    )

    assert result.attempted is True
    assert result.succeeded is True
    assert result.upgraded is False
    assert result.reason == "below_confidence_floor"

    row = db_session.execute(
        select(Diagnosis).where(Diagnosis.order_id == "order_low_confidence")
    ).scalar_one()
    assert row.succeeded is True
    assert row.confidence == 0.3

    assert (
        db_session.execute(
            select(Decision).where(Decision.order_id == "order_low_confidence")
        ).first()
        is None
    )


def test_confident_actionable_diagnosis_authorizes_a_decision_and_enqueues_it(db_session) -> None:
    _seed_payment(db_session, "order_recoverable", contact="+911234567890", amount_paise=50_000)
    settings = make_settings(
        anthropic_api_key="fake",
        min_diagnosis_confidence=0.7,
        human_approval_threshold_paise=2_500_000,
    )
    client = _client_returning(
        {
            "category": "insufficient_funds",
            "confidence": 0.9,
            "reasoning": "matches a known low-balance decline pattern in the evidence",
            "cited_evidence_ids": ["E1"],
            "suggested_intervention": "send_payment_link",
        }
    )

    result = diagnose_and_decide(db_session, "order_recoverable", settings, now=_NOW, client=client)

    assert result.attempted is True
    assert result.succeeded is True
    assert result.upgraded is True
    assert result.reason == "PROPOSAL_AUTHORIZED"

    decision = db_session.execute(
        select(Decision).where(Decision.order_id == "order_recoverable")
    ).scalar_one()
    assert decision.authorized_intervention == "send_payment_link"
    assert decision.overridden is False
    assert decision.diagnosis_id is not None

    outbox_entry = db_session.execute(
        select(OutboxEntry).where(OutboxEntry.decision_id == decision.id)
    ).scalar_one()
    assert outbox_entry.status == "pending"


def test_policy_engine_still_overrides_a_contextually_wrong_llm_suggestion(db_session) -> None:
    """infra_outage is not customer_actionable -- even though
    send_payment_link is a real, schema-valid intervention, the policy
    engine's CATEGORY_NOT_CUSTOMER_ACTIONABLE gate must still override it
    to the category's safe default (wait), exactly as it would for a
    Stage 4 category-rules proposal. This is designed failure #2 from
    CLAUDE.md, exercised through the LLM path specifically."""
    _seed_payment(db_session, "order_outage", amount_paise=50_000)
    settings = make_settings(anthropic_api_key="fake")
    client = _client_returning(
        {
            "category": "infra_outage",
            "confidence": 0.85,
            "reasoning": "evidence shows a spike of identical errors consistent with an outage",
            "cited_evidence_ids": ["E6"],
            "suggested_intervention": "send_payment_link",
        }
    )

    result = diagnose_and_decide(db_session, "order_outage", settings, now=_NOW, client=client)

    assert result.succeeded is True
    assert result.reason == "CATEGORY_NOT_CUSTOMER_ACTIONABLE"

    decision = db_session.execute(
        select(Decision).where(Decision.order_id == "order_outage")
    ).scalar_one()
    assert decision.proposed_intervention == "send_payment_link"
    assert decision.authorized_intervention == "wait"
    assert decision.overridden is True
    assert decision.rule_id == "CATEGORY_NOT_CUSTOMER_ACTIONABLE"

    assert (
        db_session.execute(
            select(OutboxEntry).where(OutboxEntry.decision_id == decision.id)
        ).first()
        is None
    )
