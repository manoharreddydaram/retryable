"""Writes an OutboxEntry in the same transaction as the Decision it belongs
to, for every authorized intervention the dispatcher actually knows how to
execute. A decision resolving to wait/suppress/escalate_to_human never gets
a row -- there's nothing to dispatch.

_DISPATCHABLE is deliberately narrower than "every intervention flagged
calls_razorpay in the catalog": verify_status is correctly gated by the
policy engine since Stage 4 (see test_verify_status_during_an_outage_is_not_blocked),
but wiring its execution -- fetch real status, then decide what that
implies -- is a clean extension for later, not something to half-build now.

Timing is taken entirely from decision.decided_at rather than a fresh
datetime.now(UTC) call here. The two must agree: a decision made "now" (or
at a synthetic time Stage 6's eval harness supplies) must produce an outbox
entry immediately eligible relative to that same moment, not whatever the
wall clock happens to read when this function runs microseconds later.
Every dispatchable decision authorized here is an immediate send by
construction (a quiet-hours-deferred proposal resolves to WAIT, not
SEND_PAYMENT_LINK, so it never reaches _DISPATCHABLE at all).
"""

from sqlalchemy.orm import Session

from src.execute.models import OutboxEntry
from src.policy.catalog import Intervention, resolve_intervention
from src.policy.models import Decision

_DISPATCHABLE = {Intervention.SEND_PAYMENT_LINK}


def enqueue_if_needed(session: Session, decision: Decision) -> OutboxEntry | None:
    intervention = resolve_intervention(decision.authorized_intervention)
    if intervention not in _DISPATCHABLE:
        return None

    when = decision.decided_at
    entry = OutboxEntry(
        decision_id=decision.id,
        idempotency_key=f"rtx-{decision.id.hex}",
        intervention=decision.authorized_intervention,
        order_id=decision.order_id,
        amount_paise=decision.amount_paise,
        status="pending",
        attempts=0,
        next_attempt_at=when,
        created_at=when,
        updated_at=when,
    )
    session.add(entry)
    return entry
