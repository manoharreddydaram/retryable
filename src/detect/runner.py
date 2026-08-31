"""Runs one full detection pass: computes the current window's cohort
stats (system-wide, plus a per-category failure-share for each taxonomy
category) and evaluates each through service.py. Mirrors
src/execute/dispatcher.py and src/diagnose/runner.py's run_once() shape --
the same "gather what's eligible, process it, summarize" pattern applied to
a statistics pass instead of a dispatch or diagnosis pass.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from src.config import Settings
from src.detect.cohorts import category_share_stats, overall_stats
from src.detect.service import evaluate_cohort


@dataclass
class DetectorRunSummary:
    cohorts_evaluated: int = 0
    fired: int = 0
    fired_cohorts: list[str] = field(default_factory=list)
    suppressed_reasons: dict[str, int] = field(default_factory=dict)


def run_once(
    session: Session, settings: Settings, now: datetime | None = None
) -> DetectorRunSummary:
    now = now or datetime.now(UTC)
    window_start = now - timedelta(minutes=settings.detector_window_minutes)

    all_stats = [
        overall_stats(session, window_start, now),
        *category_share_stats(session, window_start, now),
    ]

    summary = DetectorRunSummary()
    for stats in all_stats:
        result = evaluate_cohort(session, stats, settings, window_start, now)
        summary.cohorts_evaluated += 1
        if result.fired:
            summary.fired += 1
            summary.fired_cohorts.append(stats.cohort)
        elif result.run.suppressed_reason:
            reason = result.run.suppressed_reason
            summary.suppressed_reasons[reason] = summary.suppressed_reasons.get(reason, 0) + 1

    return summary
