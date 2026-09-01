"""GET /api/decisions/{decision_id} -- the Decision Detail screen: one
decision's full rule trace, its diagnosis (if the LLM was involved), its
outbox status (if it was ever dispatchable), and the ledger entries
recorded for it. This is what CLAUDE.md means by "every executed action
carries the ID of the rule that authorised it" made visible, not just
storable.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import (
    DecisionDetailResponse,
    DiagnosisDetail,
    LedgerEntrySummary,
    OutboxSummary,
    PaymentSummary,
)
from src.db.base import get_db
from src.diagnose.models import Diagnosis
from src.execute.models import OutboxEntry
from src.ingest.models import Payment
from src.ledger.models import LedgerEntry
from src.policy.models import Decision

router = APIRouter()


@router.get("/api/decisions/{decision_id}", response_model=DecisionDetailResponse)
def get_decision(
    decision_id: UUID,
    session: Session = Depends(get_db),  # noqa: B008 -- FastAPI's DI mechanism
) -> DecisionDetailResponse:
    decision = session.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision_not_found")

    payment = session.get(Payment, decision.order_id)

    diagnosis = None
    if decision.diagnosis_id is not None:
        diagnosis_row = session.get(Diagnosis, decision.diagnosis_id)
        if diagnosis_row is not None:
            diagnosis = DiagnosisDetail(
                id=diagnosis_row.id,
                prompt_version=diagnosis_row.prompt_version,
                prompt_hash=diagnosis_row.prompt_hash,
                model=diagnosis_row.model,
                reasoning=diagnosis_row.reasoning,
                cited_evidence_ids=diagnosis_row.cited_evidence_ids,
                evidence_bundle=diagnosis_row.evidence_bundle,
                suggested_intervention=diagnosis_row.suggested_intervention,
                created_at=diagnosis_row.created_at,
            )

    outbox_row = session.execute(
        select(OutboxEntry).where(OutboxEntry.decision_id == decision.id)
    ).scalar_one_or_none()
    outbox = (
        OutboxSummary(
            status=outbox_row.status,
            attempts=outbox_row.attempts,
            last_error=outbox_row.last_error,
            razorpay_short_url=outbox_row.razorpay_short_url,
            next_attempt_at=outbox_row.next_attempt_at,
            updated_at=outbox_row.updated_at,
        )
        if outbox_row
        else None
    )

    ledger_rows = (
        session.execute(
            select(LedgerEntry)
            .where(LedgerEntry.entity_type == "decision", LedgerEntry.entity_id == str(decision.id))
            .order_by(LedgerEntry.seq.asc())
        )
        .scalars()
        .all()
    )

    return DecisionDetailResponse(
        id=decision.id,
        order_id=decision.order_id,
        payer_contact=decision.payer_contact,
        category=decision.category,
        confidence=decision.confidence,
        amount_paise=decision.amount_paise,
        proposed_intervention=decision.proposed_intervention,
        authorized_intervention=decision.authorized_intervention,
        overridden=decision.overridden,
        rule_id=decision.rule_id,
        reason=decision.reason,
        retry_at=decision.retry_at,
        decided_at=decision.decided_at,
        payment=PaymentSummary(
            order_id=payment.order_id,
            status=payment.status,
            method=payment.method,
            currency=payment.currency,
            error_code=payment.error_code,
            error_reason=payment.error_reason,
        ),
        diagnosis=diagnosis,
        outbox=outbox,
        ledger_entries=[
            LedgerEntrySummary(
                seq=e.seq,
                entry_id=e.entry_id,
                created_at=e.created_at,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                event_type=e.event_type,
                actor=e.actor,
                payload=e.payload,
                prev_hash=e.prev_hash,
                this_hash=e.this_hash,
            )
            for e in ledger_rows
        ],
    )
