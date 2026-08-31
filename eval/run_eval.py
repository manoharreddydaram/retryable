"""Orchestrates one evaluation run: generate a batch, split it into
treatment/control arms, run each through its respective decision path, run
the real dispatcher against the real Razorpay client, simulate payer
responses, compute metrics, and write the result to eval/results/.

Every number here is reproducible by re-running with the same --seed:
batch composition, arm assignment, and simulated conversions are all
seeded. Razorpay's own object IDs are not, and cannot be -- a fresh run
creates fresh payment links -- but the methodology and its outcome
distribution are exactly reproducible.

Usage:
    python -m eval.run_eval [--seed 42] [--batch-size 150]
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from eval.batch_generator import generate_batch, split_arms
from eval.control_arm import enqueue_control_arm_retry
from eval.metrics import EvalMetrics, compute_metrics
from src.config import Settings, get_settings
from src.db.base import SessionLocal
from src.execute.dispatcher import run_once
from src.execute.razorpay_client import RazorpayClient
from src.ingest.service import ingest_webhook

_RESULTS_PATH = Path(__file__).parent / "results" / "latest_run.json"
_MAX_DISPATCH_ROUNDS = (
    20  # a healthy run finishes in 1-2; this is a hard safety cap, not an expectation
)


def run_evaluation(
    session: Session,
    client: RazorpayClient,
    settings: Settings,
    *,
    seed: int,
    batch_size: int,
    treatment_share: float = 0.7,
) -> EvalMetrics:
    batch = generate_batch(batch_size, seed=seed)
    treatment, control = split_arms(batch, seed=seed, treatment_share=treatment_share)

    for failure in treatment:
        ingest_webhook(
            session,
            event_id=f"eval-{failure.order_id}",
            raw_body=failure.to_webhook_envelope(),
            settings=settings,
            now=failure.occurred_at,
        )

    for failure in control:
        ingest_webhook(
            session,
            event_id=f"eval-{failure.order_id}",
            raw_body=failure.to_webhook_envelope(),
            settings=settings,
            skip_policy=True,
            now=failure.occurred_at,
        )
        enqueue_control_arm_retry(
            session,
            order_id=failure.order_id,
            payer_contact=failure.payer_contact,
            category=failure.true_category,
            amount_paise=failure.amount_paise,
            occurred_at=failure.occurred_at,
        )

    session.flush()

    for _ in range(_MAX_DISPATCH_ROUNDS):
        summary = run_once(session, client, settings, limit=200)
        if summary.claimed == 0:
            break

    return compute_metrics(
        session,
        seed=seed,
        treatment=treatment,
        control=control,
        max_touches_per_payer_7d=settings.max_touches_per_payer_7d,
        intervention_cost_paise=settings.intervention_cost_paise,
    )


def write_results(metrics: EvalMetrics) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": metrics.seed,
        "batch_size": metrics.batch_size,
        "treatment": asdict(metrics.treatment)
        | {
            "gross_recovery_rate": metrics.treatment.gross_recovery_rate,
            "wasted_attempt_rate": metrics.treatment.wasted_attempt_rate,
        },
        "control": asdict(metrics.control)
        | {
            "gross_recovery_rate": metrics.control.gross_recovery_rate,
            "wasted_attempt_rate": metrics.control.wasted_attempt_rate,
        },
        "incremental_lift": metrics.incremental_lift,
        "incremental_lift_ci95": list(metrics.incremental_lift_ci95),
        "intervention_cost_paise": metrics.intervention_cost_paise,
        "net_recovered_paise": metrics.net_recovered_paise,
        "cost_per_recovered_rupee": metrics.cost_per_recovered_rupee,
        "blocked_actions": metrics.blocked_actions,
        "unresolved_exceptions": metrics.unresolved_exceptions,
        "stopping_rule_violations": metrics.stopping_rule_violations,
        "double_charge_incidents": metrics.double_charge_incidents,
        "known_reason_accuracy": metrics.known_reason_accuracy,
        "novel_string_accuracy": metrics.novel_string_accuracy,
        "pending_not_yet_dispatched": metrics.pending_not_yet_dispatched,
    }
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _row(label: str, t_value: str, c_value: str) -> str:
    return f"{label:22s} {t_value:>12s} {c_value:>12s}"


def print_summary(metrics: EvalMetrics) -> None:
    t, c = metrics.treatment, metrics.control
    print(f"seed={metrics.seed} batch_size={metrics.batch_size}\n")
    print(_row("", "treatment", "control"))
    print(
        _row(
            "revenue at risk (Rs)",
            f"{t.revenue_at_risk_paise / 100:,.0f}",
            f"{c.revenue_at_risk_paise / 100:,.0f}",
        )
    )
    print(_row("attempted sends", str(t.attempted_sends), str(c.attempted_sends)))
    print(
        _row("gross recovery rate", f"{t.gross_recovery_rate:.1%}", f"{c.gross_recovery_rate:.1%}")
    )
    print(
        _row("wasted-attempt rate", f"{t.wasted_attempt_rate:.1%}", f"{c.wasted_attempt_rate:.1%}")
    )
    print(
        _row(
            "gross recovered (Rs)",
            f"{t.gross_recovered_paise / 100:,.0f}",
            f"{c.gross_recovered_paise / 100:,.0f}",
        )
    )

    lo, hi = metrics.incremental_lift_ci95
    lift, cost = metrics.incremental_lift, metrics.net_recovered_paise / 100
    print(f"\nincremental lift (treatment - control): {lift:+.1%} (95% CI: {lo:+.1%} to {hi:+.1%})")
    print(f"net recovered after intervention cost: Rs {cost:,.0f}")
    if metrics.cost_per_recovered_rupee is not None:
        print(f"cost per recovered rupee: Rs {metrics.cost_per_recovered_rupee:.4f}")

    known, novel = metrics.known_reason_accuracy, metrics.novel_string_accuracy
    print(f"\nknown-reason accuracy: {known:.1%} (a lookup; sanity check)")
    print(f"novel-string accuracy (correctly deferred): {novel:.1%}")

    print("\nblocked actions (treatment only):")
    for rule_id, count in sorted(metrics.blocked_actions.items(), key=lambda kv: -kv[1]):
        print(f"  {rule_id}: {count}")

    print(f"\nunresolved exceptions (escalated / failed): {metrics.unresolved_exceptions}")
    print(f"stopping-rule violations (must be 0): {metrics.stopping_rule_violations}")
    print(f"double-charge incidents (must be 0): {metrics.double_charge_incidents}")

    if metrics.pending_not_yet_dispatched:
        print(
            f"\n{metrics.pending_not_yet_dispatched} entries are still pending, not yet "
            "dispatched -- likely Razorpay's test-mode rate limit or the circuit breaker "
            "paused part of this run. The metrics above only count what actually completed. "
            "Wait a minute or two and run `make dispatch` to pick up the rest, then re-read "
            "eval/results/latest_run.json for the fuller picture."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Retryable evaluation harness.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=150)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        print(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set in .env -- eval needs the real API."
        )
        return 1

    client = RazorpayClient(settings.razorpay_key_id, settings.razorpay_key_secret)

    with SessionLocal() as session:
        metrics = run_evaluation(
            session, client, settings, seed=args.seed, batch_size=args.batch_size
        )
        session.commit()

    print_summary(metrics)
    write_results(metrics)
    print(f"\nResults written to {_RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
