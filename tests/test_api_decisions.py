"""Tests for GET /api/decisions/{decision_id}."""

import uuid
from datetime import UTC, datetime

from src.diagnose.models import Diagnosis
from src.execute.outbox import enqueue_if_needed
from src.ingest.models import Payment
from src.ledger.writer import append_entry
from src.policy.models import Decision

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _seed_payment(session, order_id: str, **overrides) -> None:
    defaults = dict(
        order_id=order_id,
        status="failed",
        latest_payment_id=f"pay_{order_id}",
        amount_paise=10_000,
        currency="INR",
        method="card",
        error_code="BAD_OTP",
        error_reason="incorrect_otp",
        category="input_error_retriable",
        raw_payload={},
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(overrides)
    session.add(Payment(**defaults))
    session.flush()


def _seed_decision(session, order_id: str, **overrides) -> Decision:
    defaults = dict(
        id=uuid.uuid4(),
        order_id=order_id,
        payer_contact=None,
        category="input_error_retriable",
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


def test_unknown_decision_id_is_404(api_client) -> None:
    response = api_client.get(f"/api/decisions/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "decision_not_found"


def test_decision_detail_includes_the_rule_trace_and_payment(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_dd_order")
    decision = _seed_decision(db_session, "stage9_dd_order", rule_id="QUIET_HOURS", overridden=True)

    response = api_client.get(f"/api/decisions/{decision.id}")
    body = response.json()

    assert response.status_code == 200
    assert body["rule_id"] == "QUIET_HOURS"
    assert body["overridden"] is True
    assert body["payment"]["order_id"] == "stage9_dd_order"
    assert body["payment"]["error_reason"] == "incorrect_otp"
    assert body["diagnosis"] is None
    assert body["outbox"] is None
    assert body["ledger_entries"] == []


def test_decision_detail_includes_diagnosis_when_llm_sourced(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_dd_llm", category="unknown")
    diagnosis = Diagnosis(
        id=uuid.uuid4(),
        order_id="stage9_dd_llm",
        prompt_version="diagnose_v1",
        prompt_hash="x" * 64,
        model="claude-opus-5",
        evidence_bundle={"items": [{"id": "E1", "description": "test evidence"}]},
        succeeded=True,
        reasoning="matches a known pattern",
        cited_evidence_ids=["E1"],
        suggested_intervention="send_payment_link",
        category="insufficient_funds",
        confidence=0.9,
        raw_response={},
        created_at=_NOW,
    )
    db_session.add(diagnosis)
    db_session.flush()
    decision = _seed_decision(db_session, "stage9_dd_llm", diagnosis_id=diagnosis.id)

    response = api_client.get(f"/api/decisions/{decision.id}")
    body = response.json()

    assert body["diagnosis"]["id"] == str(diagnosis.id)
    assert body["diagnosis"]["reasoning"] == "matches a known pattern"
    assert body["diagnosis"]["cited_evidence_ids"] == ["E1"]
    assert body["diagnosis"]["model"] == "claude-opus-5"


def test_decision_detail_includes_outbox_status(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_dd_outbox")
    decision = _seed_decision(db_session, "stage9_dd_outbox")
    enqueue_if_needed(db_session, decision)

    response = api_client.get(f"/api/decisions/{decision.id}")

    assert response.json()["outbox"]["status"] == "pending"


def test_decision_detail_includes_only_its_own_ledger_entries(api_client, db_session) -> None:
    _seed_payment(db_session, "stage9_dd_ledger_a")
    _seed_payment(db_session, "stage9_dd_ledger_b")
    decision_a = _seed_decision(db_session, "stage9_dd_ledger_a")
    decision_b = _seed_decision(db_session, "stage9_dd_ledger_b")
    append_entry(
        db_session,
        entity_type="decision",
        entity_id=str(decision_a.id),
        event_type="decision.PROPOSAL_AUTHORIZED",
        actor="system:test",
        payload={"note": "a"},
    )
    append_entry(
        db_session,
        entity_type="decision",
        entity_id=str(decision_b.id),
        event_type="decision.PROPOSAL_AUTHORIZED",
        actor="system:test",
        payload={"note": "b"},
    )

    response = api_client.get(f"/api/decisions/{decision_a.id}")
    entries = response.json()["ledger_entries"]

    assert len(entries) == 1
    assert entries[0]["payload"]["note"] == "a"
