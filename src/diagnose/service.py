"""Orchestrates one re-diagnosis: check eligibility, bundle evidence, call
the LLM, persist a full audit record either way, and -- only on a
confident, citation-valid success -- run the result through the exact same
policy engine as every other proposal, authorizing a new Decision (and, if
applicable, a new outbox entry) that supersedes the original
escalate_to_human.

Only ever invoked for orders the deterministic classifier could not
resolve (category == "unknown"). Re-diagnosing an already-confidently-
classified failure would spend real money asking a question this project
already has a free, instant, 100% reproducible answer to -- see the
AI-usage boundaries in README.md.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.classify.rules import category_profiles
from src.config import Settings
from src.diagnose.client import DiagnosisFailed, call_llm
from src.diagnose.evidence import EvidenceBundle, build_evidence_bundle
from src.diagnose.models import Diagnosis
from src.diagnose.prompts import PROMPT_VERSION, prompt_hash
from src.diagnose.schemas import DiagnosisOutput
from src.execute.outbox import enqueue_if_needed
from src.ingest.models import Payment
from src.ingest.schemas import RazorpayPaymentEntity
from src.ledger.writer import append_entry
from src.policy.context import touches_in_window
from src.policy.engine import DecisionInput, Proposal, decide
from src.policy.models import Decision


@dataclass(frozen=True)
class DiagnoseResult:
    attempted: bool
    succeeded: bool
    upgraded: bool  # produced a new, authorized (non-overridden) decision
    reason: str | None = None


def diagnose_and_decide(
    session: Session,
    order_id: str,
    settings: Settings,
    now: datetime | None = None,
    client: anthropic.Anthropic | None = None,
) -> DiagnoseResult:
    now = now or datetime.now(UTC)

    payment = session.get(Payment, order_id)
    if payment is None or payment.status != "failed" or payment.category != "unknown":
        return DiagnoseResult(
            attempted=False, succeeded=False, upgraded=False, reason="not_eligible"
        )

    already_diagnosed = session.execute(
        select(Diagnosis.id).where(Diagnosis.order_id == order_id)
    ).scalar_one_or_none()
    if already_diagnosed is not None:
        return DiagnoseResult(
            attempted=False, succeeded=False, upgraded=False, reason="already_diagnosed"
        )

    payment_entity = RazorpayPaymentEntity(
        id=payment.latest_payment_id,
        amount=payment.amount_paise,
        currency=payment.currency,
        status=payment.status,
        order_id=payment.order_id,
        method=payment.method,
        contact=payment.payer_contact,
        error_code=payment.error_code,
        error_reason=payment.error_reason,
    )
    bundle = build_evidence_bundle(session, payment_entity, now)

    try:
        output, used_prompt_hash, raw_response = call_llm(bundle, settings, client=client)
    except DiagnosisFailed as exc:
        _record_diagnosis(
            session,
            order_id,
            bundle,
            settings,
            succeeded=False,
            failure_reason=exc.reason,
            output=None,
            raw_response={},
            used_prompt_hash=prompt_hash(),
        )
        return DiagnoseResult(attempted=True, succeeded=False, upgraded=False, reason=exc.reason)

    diagnosis_row = _record_diagnosis(
        session,
        order_id,
        bundle,
        settings,
        succeeded=True,
        failure_reason=None,
        output=output,
        raw_response=raw_response,
        used_prompt_hash=used_prompt_hash,
    )

    if output.confidence < settings.min_diagnosis_confidence:
        return DiagnoseResult(
            attempted=True, succeeded=True, upgraded=False, reason="below_confidence_floor"
        )

    ctx = DecisionInput(
        category=output.category,
        profile=category_profiles()[output.category],
        confidence=output.confidence,
        amount_paise=payment.amount_paise,
        touches_in_window=touches_in_window(session, payment.payer_contact, now=now),
        interventions_dispatched_in_batch=0,
        now=now,
    )
    proposal = Proposal(intervention=output.suggested_intervention.value, source="llm")
    outcome = decide(proposal, ctx, settings)

    decision_row = Decision(
        id=uuid.uuid4(),
        order_id=order_id,
        payer_contact=payment.payer_contact,
        category=output.category.value,
        confidence=output.confidence,
        amount_paise=payment.amount_paise,
        proposed_intervention=outcome.proposed_intervention,
        authorized_intervention=outcome.authorized_intervention.value,
        overridden=outcome.overridden,
        rule_id=outcome.rule_id,
        reason=outcome.reason,
        retry_at=outcome.retry_at,
        decided_at=now,
        diagnosis_id=diagnosis_row.id,
    )
    session.add(decision_row)
    session.flush()

    enqueue_if_needed(session, decision_row)

    append_entry(
        session,
        entity_type="decision",
        entity_id=str(decision_row.id),
        event_type=f"decision.{outcome.rule_id.lower()}",
        actor="system:diagnose",
        payload={
            "order_id": order_id,
            "category": output.category.value,
            "confidence": output.confidence,
            "proposed": outcome.proposed_intervention,
            "authorized": outcome.authorized_intervention.value,
            "overridden": outcome.overridden,
            "rule_id": outcome.rule_id,
            "reasoning": output.reasoning,
            "cited_evidence_ids": output.cited_evidence_ids,
        },
    )

    return DiagnoseResult(
        attempted=True, succeeded=True, upgraded=not outcome.overridden, reason=outcome.rule_id
    )


def _record_diagnosis(
    session: Session,
    order_id: str,
    bundle: EvidenceBundle,
    settings: Settings,
    *,
    succeeded: bool,
    failure_reason: str | None,
    output: DiagnosisOutput | None,
    raw_response: dict,
    used_prompt_hash: str,
) -> Diagnosis:
    row = Diagnosis(
        id=uuid.uuid4(),
        order_id=order_id,
        prompt_version=PROMPT_VERSION,
        prompt_hash=used_prompt_hash,
        model=settings.anthropic_model,
        evidence_bundle={
            "items": [{"id": item.id, "description": item.description} for item in bundle.items]
        },
        succeeded=succeeded,
        failure_reason=failure_reason,
        category=output.category.value if output else None,
        confidence=output.confidence if output else None,
        reasoning=output.reasoning if output else None,
        cited_evidence_ids=output.cited_evidence_ids if output else None,
        suggested_intervention=output.suggested_intervention.value if output else None,
        raw_response=raw_response,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row
