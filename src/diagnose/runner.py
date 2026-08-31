"""Finds every order the deterministic classifier could not resolve and
hasn't already been diagnosed, and runs each through diagnose_and_decide().

Mirrors src/execute/dispatcher.py's run_once() shape deliberately: the same
"claim what's eligible, process it, summarize" pattern applied to LLM calls
instead of Razorpay calls. A webhook handler cannot afford to block on an
LLM round-trip (Razorpay expects a response within 5 seconds, confirmed
against their own docs in Stage 2), so diagnosis runs as this separate,
on-demand pass rather than inline during ingest.
"""

from dataclasses import dataclass, field

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import Settings
from src.diagnose.models import Diagnosis
from src.diagnose.service import diagnose_and_decide
from src.ingest.models import Payment


@dataclass
class DiagnoseRunSummary:
    considered: int = 0
    succeeded: int = 0
    upgraded: int = 0
    failed: int = 0
    failure_reasons: dict[str, int] = field(default_factory=dict)


def run_once(
    session: Session, settings: Settings, limit: int = 50, client: anthropic.Anthropic | None = None
) -> DiagnoseRunSummary:
    already_diagnosed = select(Diagnosis.order_id)
    candidate_order_ids = (
        session.execute(
            select(Payment.order_id)
            .where(Payment.status == "failed", Payment.category == "unknown")
            .where(Payment.order_id.not_in(already_diagnosed))
            .limit(limit)
        )
        .scalars()
        .all()
    )

    summary = DiagnoseRunSummary()
    for order_id in candidate_order_ids:
        summary.considered += 1
        result = diagnose_and_decide(session, order_id, settings, client=client)

        if not result.attempted:
            continue
        if result.succeeded:
            summary.succeeded += 1
            if result.upgraded:
                summary.upgraded += 1
        else:
            summary.failed += 1
            reason = result.reason or "unknown"
            summary.failure_reasons[reason] = summary.failure_reasons.get(reason, 0) + 1

    return summary
