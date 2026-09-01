"""GET /api/triage -- the Live Triage screen's data: recent payments and
whatever the system most recently decided about each. See schemas.py's
module docstring: read-only projection, no write path.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import TriageRow
from src.db.base import get_db
from src.execute.models import OutboxEntry
from src.ingest.models import Payment
from src.policy.models import Decision

router = APIRouter()


@router.get("/api/triage", response_model=list[TriageRow])
def list_triage(
    limit: int = 50,
    session: Session = Depends(get_db),  # noqa: B008 -- FastAPI's DI mechanism
) -> list[TriageRow]:
    payments = (
        session.execute(select(Payment).order_by(Payment.updated_at.desc()).limit(limit))
        .scalars()
        .all()
    )

    rows = []
    for payment in payments:
        decision = session.execute(
            select(Decision)
            .where(Decision.order_id == payment.order_id)
            .order_by(Decision.decided_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        outbox_status = None
        if decision is not None:
            outbox_entry = session.execute(
                select(OutboxEntry).where(OutboxEntry.decision_id == decision.id)
            ).scalar_one_or_none()
            outbox_status = outbox_entry.status if outbox_entry else None

        rows.append(
            TriageRow(
                order_id=payment.order_id,
                status=payment.status,
                amount_paise=payment.amount_paise,
                method=payment.method,
                error_reason=payment.error_reason,
                category=payment.category,
                updated_at=payment.updated_at,
                decision_id=decision.id if decision else None,
                authorized_intervention=decision.authorized_intervention if decision else None,
                overridden=decision.overridden if decision else None,
                rule_id=decision.rule_id if decision else None,
                via_llm=decision.diagnosis_id is not None if decision else False,
                outbox_status=outbox_status,
            )
        )
    return rows
