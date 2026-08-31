"""Computes every metric EVALUATION.md commits to reporting, from the real
Decision/OutboxEntry/Payment rows a batch produced plus the payer
simulator's (also reproducible) conversion outcomes. Every number here is
an aggregate over the whole batch -- nothing is a hand-picked example.
"""

import math
from dataclasses import dataclass

from scipy import stats
from sqlalchemy import select
from sqlalchemy.orm import Session

from eval.batch_generator import SyntheticFailure
from eval.control_arm import CONTROL_ARM_RULE_ID
from eval.payer_simulator import simulate_conversion
from src.execute.models import OutboxEntry
from src.ingest.models import Payment
from src.policy.models import Decision


@dataclass
class ArmMetrics:
    revenue_at_risk_paise: int = 0
    attempted_sends: int = 0
    converted_sends: int = 0
    gross_recovered_paise: int = 0

    @property
    def gross_recovery_rate(self) -> float:
        return self.converted_sends / self.attempted_sends if self.attempted_sends else 0.0

    @property
    def wasted_attempt_rate(self) -> float:
        if self.attempted_sends == 0:
            return 0.0
        return (self.attempted_sends - self.converted_sends) / self.attempted_sends


@dataclass
class EvalMetrics:
    seed: int
    batch_size: int
    treatment: ArmMetrics
    control: ArmMetrics
    incremental_lift: float
    incremental_lift_ci95: tuple[float, float]
    intervention_cost_paise: int
    net_recovered_paise: int
    cost_per_recovered_rupee: float | None
    blocked_actions: dict[str, int]
    unresolved_exceptions: int
    stopping_rule_violations: int
    double_charge_incidents: int
    known_reason_accuracy: float
    novel_string_accuracy: float
    pending_not_yet_dispatched: int


def two_proportion_ci95(p1: float, n1: int, p2: float, n2: int) -> tuple[float, float]:
    """Wald confidence interval for the difference of two proportions."""
    if n1 == 0 or n2 == 0:
        return (0.0, 0.0)
    diff = p1 - p2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = stats.norm.ppf(0.975)
    return (diff - z * se, diff + z * se)


def compute_metrics(
    session: Session,
    seed: int,
    treatment: list[SyntheticFailure],
    control: list[SyntheticFailure],
    max_touches_per_payer_7d: int,
    intervention_cost_paise: int,
) -> EvalMetrics:
    treatment_arm = _arm_metrics(session, seed, treatment, timing="immediate")
    control_arm = _arm_metrics(session, seed, control, timing="delayed_1h")

    lift = treatment_arm.gross_recovery_rate - control_arm.gross_recovery_rate
    ci = two_proportion_ci95(
        treatment_arm.gross_recovery_rate,
        treatment_arm.attempted_sends,
        control_arm.gross_recovery_rate,
        control_arm.attempted_sends,
    )

    total_sends = treatment_arm.attempted_sends + control_arm.attempted_sends
    total_recovered = treatment_arm.gross_recovered_paise + control_arm.gross_recovered_paise
    total_cost = total_sends * intervention_cost_paise
    net_recovered = total_recovered - total_cost
    cost_per_recovered_rupee = (
        (total_cost / 100) / (total_recovered / 100) if total_recovered else None
    )

    all_orders = [f.order_id for f in treatment + control]
    blocked_actions = _blocked_action_counts(session, all_orders)
    unresolved = _unresolved_exception_count(session, all_orders)
    touch_violations = _stopping_rule_violations(session, all_orders, max_touches_per_payer_7d)
    double_charges = _double_charge_incidents(session, all_orders)
    known_acc, novel_acc = _classifier_accuracy(session, treatment + control)
    still_pending = _pending_count(session, all_orders)

    return EvalMetrics(
        seed=seed,
        batch_size=len(treatment) + len(control),
        treatment=treatment_arm,
        control=control_arm,
        incremental_lift=lift,
        incremental_lift_ci95=ci,
        intervention_cost_paise=intervention_cost_paise,
        net_recovered_paise=net_recovered,
        cost_per_recovered_rupee=cost_per_recovered_rupee,
        blocked_actions=blocked_actions,
        unresolved_exceptions=unresolved,
        stopping_rule_violations=touch_violations,
        double_charge_incidents=double_charges,
        known_reason_accuracy=known_acc,
        novel_string_accuracy=novel_acc,
        pending_not_yet_dispatched=still_pending,
    )


def _arm_metrics(
    session: Session, seed: int, failures: list[SyntheticFailure], timing: str
) -> ArmMetrics:
    metrics = ArmMetrics(revenue_at_risk_paise=sum(f.amount_paise for f in failures))
    order_ids = [f.order_id for f in failures]
    if not order_ids:
        return metrics

    completed = (
        session.execute(
            select(OutboxEntry).where(
                OutboxEntry.order_id.in_(order_ids), OutboxEntry.status == "complete"
            )
        )
        .scalars()
        .all()
    )
    failures_by_order = {f.order_id: f for f in failures}

    for entry in completed:
        failure = failures_by_order[entry.order_id]
        metrics.attempted_sends += 1
        converted = simulate_conversion(failure.true_category, timing, seed, failure.order_id)
        if converted:
            metrics.converted_sends += 1
            metrics.gross_recovered_paise += entry.amount_paise

    return metrics


def _blocked_action_counts(session: Session, order_ids: list[str]) -> dict[str, int]:
    if not order_ids:
        return {}
    rows = (
        session.execute(
            select(Decision.rule_id)
            .where(Decision.order_id.in_(order_ids), Decision.overridden.is_(True))
            .where(Decision.rule_id != CONTROL_ARM_RULE_ID)
        )
        .scalars()
        .all()
    )
    counts: dict[str, int] = {}
    for rule_id in rows:
        counts[rule_id] = counts.get(rule_id, 0) + 1
    return counts


def _unresolved_exception_count(session: Session, order_ids: list[str]) -> int:
    if not order_ids:
        return 0
    escalated = (
        session.execute(
            select(Decision.id).where(
                Decision.order_id.in_(order_ids),
                Decision.authorized_intervention == "escalate_to_human",
            )
        )
        .scalars()
        .all()
    )
    stuck = (
        session.execute(
            select(OutboxEntry.id).where(
                OutboxEntry.order_id.in_(order_ids), OutboxEntry.status == "failed_permanently"
            )
        )
        .scalars()
        .all()
    )
    return len(escalated) + len(stuck)


def _stopping_rule_violations(session: Session, order_ids: list[str], max_touches: int) -> int:
    """Independent, post-hoc verification that no payer exceeded the touch
    cap within this batch -- checked directly against the executed record,
    not just trusted because the policy engine's own gate should prevent it."""
    if not order_ids:
        return 0
    rows = session.execute(
        select(Decision.payer_contact, OutboxEntry.id)
        .join(OutboxEntry, OutboxEntry.decision_id == Decision.id)
        .where(
            Decision.order_id.in_(order_ids),
            OutboxEntry.status == "complete",
            Decision.payer_contact.is_not(None),
        )
    ).all()
    counts: dict[str, int] = {}
    for payer_contact, _ in rows:
        counts[payer_contact] = counts.get(payer_contact, 0) + 1
    return sum(1 for count in counts.values() if count > max_touches)


def _double_charge_incidents(session: Session, order_ids: list[str]) -> int:
    """More than one genuinely new (non-recovered) completed send for the
    same order would mean two payment links for one failure -- structurally
    prevented by one-Decision-per-order plus the reference_id uniqueness
    Stage 5 relies on, checked here rather than only assumed."""
    if not order_ids:
        return 0
    rows = (
        session.execute(
            select(OutboxEntry.order_id).where(
                OutboxEntry.order_id.in_(order_ids), OutboxEntry.status == "complete"
            )
        )
        .scalars()
        .all()
    )
    counts: dict[str, int] = {}
    for order_id in rows:
        counts[order_id] = counts.get(order_id, 0) + 1
    return sum(1 for count in counts.values() if count > 1)


def _pending_count(session: Session, order_ids: list[str]) -> int:
    """How many of this batch's outbox entries are still awaiting dispatch --
    typically nonzero only when Razorpay's (undocumented) test-mode rate
    limit or the circuit breaker paused part of the run. Not an error: a
    later `make dispatch` will pick these up once the pause has passed.
    Surfaced explicitly so a partially-drained batch is never mistaken for
    a fully-measured one."""
    if not order_ids:
        return 0
    rows = (
        session.execute(
            select(OutboxEntry.id).where(
                OutboxEntry.order_id.in_(order_ids), OutboxEntry.status == "pending"
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


def _classifier_accuracy(session: Session, batch: list[SyntheticFailure]) -> tuple[float, float]:
    """known_reason_accuracy is trivially expected at 1.0 -- it's a lookup,
    not a prediction -- and is reported as a sanity check, not an
    achievement. novel_string_accuracy measures the one thing this
    deterministic stage can actually be graded on for unseen strings:
    whether it honestly reports "unknown" rather than guessing wrong. Both
    become genuinely interesting once Stage 7's LLM starts resolving some
    of today's "unknown" cases to a real category."""
    order_ids = [f.order_id for f in batch]
    if not order_ids:
        return (0.0, 0.0)

    rows = session.execute(
        select(Payment.order_id, Payment.category).where(Payment.order_id.in_(order_ids))
    ).all()
    actual_category = dict(rows)

    known = [f for f in batch if f.true_category != "unknown"]
    novel = [f for f in batch if f.true_category == "unknown"]

    known_correct = sum(1 for f in known if actual_category.get(f.order_id) == f.true_category)
    novel_correct = sum(1 for f in novel if actual_category.get(f.order_id) == "unknown")

    known_accuracy = known_correct / len(known) if known else 1.0
    novel_accuracy = novel_correct / len(novel) if novel else 1.0
    return (known_accuracy, novel_accuracy)
