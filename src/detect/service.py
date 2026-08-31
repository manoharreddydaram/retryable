"""Orchestrates one cohort's evaluation: load its tracked baseline, apply
the minimum-sample gate, run the significance test, persist a full audit
row either way, and advance the baseline for next time. Every attempt is
recorded -- gated, not-significant, or fired -- exactly as Diagnosis
records a failed LLM call: a suppressed alarm needs to be exactly as
visible after the fact as a fired one, or "the system correctly chose not
to alert" is just a claim nobody can check.

The minimum-sample gate runs before the significance test even executes,
never after: see significance.py's own docstring for why the beta-binomial
math alone cannot be trusted to reject a tiny, noisy sample on its own.

Baseline updates use an atomic upsert (INSERT ... ON CONFLICT), the same
defense applied to circuit_breaker_state in Stage 5 after a real race
surfaced there -- cheap insurance against two overlapping detector runs
touching the same cohort. The read-then-test-then-write sequence around it
is not fully race-proof (a concurrent run could test against a baseline
that's about to go stale), but this module only ever affects what gets
displayed and logged, never what gets spent -- a brief staleness window is
a proportionate risk to accept here, unlike anywhere spend is authorized.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.config import Settings
from src.detect.cohorts import CohortStats
from src.detect.ewma import update_ewma
from src.detect.models import DetectorBaseline, DetectorRun
from src.detect.significance import probability_degraded
from src.ledger.writer import append_entry


@dataclass(frozen=True)
class EvaluationResult:
    run: DetectorRun
    fired: bool


def evaluate_cohort(
    session: Session,
    stats: CohortStats,
    settings: Settings,
    window_start: datetime,
    window_end: datetime,
) -> EvaluationResult:
    observed_rate = stats.observed_count / stats.total_count if stats.total_count > 0 else 0.0
    baseline_row = session.get(DetectorBaseline, stats.cohort)

    if stats.total_count < settings.detector_min_sample_size:
        run = _record_run(
            session,
            stats,
            window_start,
            window_end,
            observed_rate=observed_rate,
            baseline_rate=baseline_row.ewma_rate if baseline_row else observed_rate,
            probability=None,
            fired=False,
            suppressed_reason="insufficient_sample",
        )
        return EvaluationResult(run=run, fired=False)

    if baseline_row is None:
        _upsert_baseline(
            session, stats.cohort, ewma_rate=observed_rate, observations=1, now=window_end
        )
        run = _record_run(
            session,
            stats,
            window_start,
            window_end,
            observed_rate=observed_rate,
            baseline_rate=observed_rate,
            probability=None,
            fired=False,
            suppressed_reason="insufficient_history",
        )
        return EvaluationResult(run=run, fired=False)

    prior_baseline_rate = baseline_row.ewma_rate
    probability = probability_degraded(
        baseline_rate=prior_baseline_rate,
        baseline_strength=settings.detector_baseline_strength,
        observed_count=stats.observed_count,
        total_count=stats.total_count,
    )
    fired = probability >= settings.detector_confidence_threshold

    new_ewma_rate = update_ewma(prior_baseline_rate, observed_rate, settings.detector_ewma_alpha)
    _upsert_baseline(
        session,
        stats.cohort,
        ewma_rate=new_ewma_rate,
        observations=baseline_row.observations + 1,
        now=window_end,
    )

    run = _record_run(
        session,
        stats,
        window_start,
        window_end,
        observed_rate=observed_rate,
        baseline_rate=prior_baseline_rate,
        probability=probability,
        fired=fired,
        suppressed_reason=None if fired else "not_significant",
    )

    if fired:
        append_entry(
            session,
            entity_type="cohort",
            entity_id=stats.cohort,
            event_type="degradation.alert_fired",
            actor="system:detect",
            payload={
                "cohort": stats.cohort,
                "observed_count": stats.observed_count,
                "total_count": stats.total_count,
                "observed_rate": observed_rate,
                "baseline_rate": prior_baseline_rate,
                "probability_degraded": probability,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        )

    return EvaluationResult(run=run, fired=fired)


def _record_run(
    session: Session,
    stats: CohortStats,
    window_start: datetime,
    window_end: datetime,
    *,
    observed_rate: float,
    baseline_rate: float,
    probability: float | None,
    fired: bool,
    suppressed_reason: str | None,
) -> DetectorRun:
    row = DetectorRun(
        id=uuid.uuid4(),
        cohort=stats.cohort,
        window_start=window_start,
        window_end=window_end,
        observed_count=stats.observed_count,
        total_count=stats.total_count,
        observed_rate=observed_rate,
        baseline_rate=baseline_rate,
        probability_degraded=probability,
        fired=fired,
        suppressed_reason=suppressed_reason,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def _upsert_baseline(
    session: Session, cohort: str, *, ewma_rate: float, observations: int, now: datetime
) -> None:
    stmt = pg_insert(DetectorBaseline).values(
        cohort=cohort, ewma_rate=ewma_rate, observations=observations, updated_at=now
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["cohort"],
        set_={
            "ewma_rate": stmt.excluded.ewma_rate,
            "observations": stmt.excluded.observations,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)
