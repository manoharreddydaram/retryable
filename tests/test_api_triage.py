"""Tests for GET /api/triage, through the real HTTP endpoint (see
conftest.py's api_client fixture)."""

import uuid
from datetime import UTC, datetime

from src.diagnose.models import Diagnosis
from src.execute.outbox import enqueue_if_needed
from src.ingest.models import Payment
from src.policy.models import Decision

# Pinned far in the future: /api/triage orders by updated_at with no window
# filter, so a realistic-looking recent timestamp could still sort behind
# genuine dev activity in this shared database (see conftest.py's db_session
# docstring) and never appear in the response at all.
_NOW = datetime(2031, 5, 1, tzinfo=UTC)


def _seed_payment(
    session, order_id: str, *, status: str = "failed", category: str | None = None
) -> None:
    session.add(
        Payment(
            order_id=order_id,
            status=status,
            latest_payment_id=f"pay_{order_id}",
            amount_paise=10_000,
            currency="INR",
            method="card",
            category=category,
            raw_payload={},
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    session.flush()


def _seed_decision(session, order_id: str, **overrides) -> Decision:
    defaults = dict(
        order_id=order_id,
        payer_contact=None,
        category="insufficient_funds",
        confidence=0.9,
        amount_paise=10_000,
        proposed_intervention="send_payment_link",
        authorized_intervention="send_payment_link",
        overridden=False,
        rule_id="PROPOSAL_AUTHORIZED",
        reason="test reason",
        decided_at=_NOW,
        diagnosis_id=None,
    )
    defaults.update(overrides)
    decision = Decision(**defaults)
    session.add(decision)
    session.flush()
    return decision


def test_triage_lists_a_seeded_payment(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_order_a")

    response = api_client.get("/api/triage")

    assert response.status_code == 200
    orders = {row["order_id"] for row in response.json()}
    assert "stage9_order_a" in orders


def test_triage_row_with_no_decision_yet_has_null_decision_fields(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_order_undecided")

    response = api_client.get("/api/triage")
    row = next(r for r in response.json() if r["order_id"] == "stage9_order_undecided")

    assert row["decision_id"] is None
    assert row["authorized_intervention"] is None
    assert row["via_llm"] is False
    assert row["outbox_status"] is None


def test_triage_shows_the_decision_and_outbox_status(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_order_decided")
    decision = _seed_decision(db_session, "stage9_order_decided")
    enqueue_if_needed(db_session, decision)

    response = api_client.get("/api/triage")
    row = next(r for r in response.json() if r["order_id"] == "stage9_order_decided")

    assert row["decision_id"] == str(decision.id)
    assert row["authorized_intervention"] == "send_payment_link"
    assert row["overridden"] is False
    assert row["rule_id"] == "PROPOSAL_AUTHORIZED"
    assert row["via_llm"] is False
    assert row["outbox_status"] == "pending"


def test_triage_flags_llm_sourced_decisions(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_order_llm", category="unknown")
    diagnosis = Diagnosis(
        id=uuid.uuid4(),
        order_id="stage9_order_llm",
        prompt_version="diagnose_v1",
        prompt_hash="x" * 64,
        model="claude-opus-5",
        evidence_bundle={"items": []},
        succeeded=True,
        raw_response={},
        created_at=_NOW,
    )
    db_session.add(diagnosis)
    db_session.flush()
    _seed_decision(db_session, "stage9_order_llm", diagnosis_id=diagnosis.id)

    response = api_client.get("/api/triage")
    row = next(r for r in response.json() if r["order_id"] == "stage9_order_llm")

    assert row["via_llm"] is True


def test_triage_respects_the_limit_parameter(api_client, db_session) -> None:
    for i in range(3):
        _seed_payment(db_session, f"stage9_order_limit_{i}")

    response = api_client.get("/api/triage", params={"limit": 1})

    assert len(response.json()) == 1
