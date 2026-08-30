"""The only module allowed to authorise spending money.

A Proposal states what someone -- Stage 4's own category-rules table today,
an LLM from Stage 7 on -- thinks should happen. decide() runs it through an
ordered sequence of gates; the first one that fires overrides the proposal,
and the override, not the original proposal, is what gets executed. Every
Decision records both what was proposed and what was actually authorized,
so a rejected proposal is exactly as visible in the audit trail as an
accepted one -- the veto is logged, not just the outcome.

Gate order is deliberate: the kill switch and confidence floor are checked
before anything else, because no other reasoning matters if either trips.
Category recoverability, operational limits (touch cap, amount, batch
ceiling) come next. Only once all of those pass do we even look at what was
actually proposed -- catalog membership, then whether this category permits
contacting the customer at all, then quiet hours.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.classify.rules import CategoryProfile
from src.classify.taxonomy import FailureCategory
from src.config import Settings
from src.policy.catalog import Intervention, intervention_profiles, resolve_intervention
from src.policy.rules_table import propose_default
from src.policy.stopping_rules import stopping_rule_reasons


@dataclass(frozen=True)
class Proposal:
    intervention: str  # raw, untrusted -- may not be a real Intervention at all
    source: str  # "category_rules" (Stage 4) | "llm" (Stage 7+)


@dataclass(frozen=True)
class DecisionInput:
    category: FailureCategory
    profile: CategoryProfile
    confidence: float
    amount_paise: int
    touches_in_window: int
    interventions_dispatched_in_batch: int
    now: datetime


@dataclass(frozen=True)
class Decision:
    proposed_intervention: str
    authorized_intervention: Intervention
    overridden: bool
    rule_id: str
    reason: str
    retry_at: datetime | None = None


def decide(proposal: Proposal, ctx: DecisionInput, settings: Settings) -> Decision:
    reasons = stopping_rule_reasons()

    if settings.kill_switch_enabled:
        return _override(proposal, "KILL_SWITCH", reasons, Intervention.SUPPRESS)

    if ctx.confidence < settings.min_diagnosis_confidence:
        return _override(proposal, "LOW_CONFIDENCE", reasons, Intervention.ESCALATE_TO_HUMAN)

    if not ctx.profile.recoverable:
        return _override(proposal, "UNRECOVERABLE_CATEGORY", reasons, Intervention.SUPPRESS)

    if ctx.touches_in_window >= settings.max_touches_per_payer_7d:
        return _override(proposal, "TOUCH_CAP_EXCEEDED", reasons, Intervention.SUPPRESS)

    if ctx.amount_paise > settings.human_approval_threshold_paise:
        return _override(
            proposal, "HUMAN_APPROVAL_REQUIRED", reasons, Intervention.ESCALATE_TO_HUMAN
        )

    if ctx.interventions_dispatched_in_batch >= settings.max_interventions_per_batch:
        return _override(proposal, "BATCH_INTERVENTION_CEILING", reasons, Intervention.SUPPRESS)

    resolved = resolve_intervention(proposal.intervention)
    if resolved is None:
        return _override(proposal, "OUT_OF_CATALOG", reasons, Intervention.ESCALATE_TO_HUMAN)

    profile = intervention_profiles()[resolved]
    if profile.requires_customer_contact and not ctx.profile.customer_actionable:
        safe_default = propose_default(ctx.category)
        return _override(proposal, "CATEGORY_NOT_CUSTOMER_ACTIONABLE", reasons, safe_default)

    if profile.requires_customer_contact and _in_quiet_hours(ctx.now, settings):
        retry_at = _next_allowed_hour(ctx.now, settings)
        return _override(proposal, "QUIET_HOURS", reasons, Intervention.WAIT, retry_at=retry_at)

    return Decision(
        proposed_intervention=proposal.intervention,
        authorized_intervention=resolved,
        overridden=False,
        rule_id="PROPOSAL_AUTHORIZED",
        reason=f"proposal from '{proposal.source}' passed every gate",
    )


def _override(
    proposal: Proposal,
    rule_id: str,
    reasons: dict[str, str],
    fallback: Intervention,
    retry_at: datetime | None = None,
) -> Decision:
    return Decision(
        proposed_intervention=proposal.intervention,
        authorized_intervention=fallback,
        overridden=True,
        rule_id=rule_id,
        reason=reasons[rule_id],
        retry_at=retry_at,
    )


def _in_quiet_hours(now: datetime, settings: Settings) -> bool:
    start, end = settings.quiet_hours_start, settings.quiet_hours_end
    hour = now.hour
    if start > end:  # window wraps midnight, e.g. 21 -> 9
        return hour >= start or hour < end
    return start <= hour < end


def _next_allowed_hour(now: datetime, settings: Settings) -> datetime:
    candidate = now.replace(hour=settings.quiet_hours_end, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
