"""The naive fixed baseline this track's bar exists to beat: retry once,
one hour later, regardless of cause. Deliberately bypasses Stage 4's policy
engine entirely -- that IS the control arm -- while still producing a real
Decision + OutboxEntry so it flows through the exact same dispatcher as
treatment. The only difference under test is the decision, not the
execution reliability underneath it.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.execute.models import OutboxEntry
from src.policy.models import Decision

CONTROL_ARM_RULE_ID = "CONTROL_ARM_NAIVE_RETRY"


def enqueue_control_arm_retry(
    session: Session,
    *,
    order_id: str,
    payer_contact: str | None,
    category: str,
    amount_paise: int,
    occurred_at: datetime,
) -> Decision:
    retry_at = occurred_at + timedelta(hours=1)
    decision = Decision(
        id=uuid.uuid4(),
        order_id=order_id,
        payer_contact=payer_contact,
        category=category,
        confidence=1.0,
        amount_paise=amount_paise,
        proposed_intervention="send_payment_link",
        authorized_intervention="send_payment_link",
        overridden=False,
        rule_id=CONTROL_ARM_RULE_ID,
        reason="Control arm: fixed retry one hour later, regardless of cause",
        retry_at=retry_at,
        decided_at=occurred_at,
    )
    session.add(decision)
    session.flush()

    session.add(
        OutboxEntry(
            decision_id=decision.id,
            idempotency_key=f"rtx-{decision.id.hex}",
            intervention="send_payment_link",
            order_id=order_id,
            amount_paise=amount_paise,
            status="pending",
            attempts=0,
            next_attempt_at=retry_at,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
    )
    return decision
