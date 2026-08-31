"""Runs the degradation detector once: evaluates the current window's
system-wide and per-category cohorts against their tracked baselines.
Meant to be invoked repeatedly (manually, or on a schedule) -- see
src/detect/runner.py's run_once() for the same poll-based reasoning as
run_dispatcher.py and run_diagnose.py.

Usage:
    python scripts/run_detect.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.db.base import SessionLocal  # noqa: E402
from src.detect.runner import run_once  # noqa: E402


def main() -> int:
    settings = get_settings()

    with SessionLocal() as session:
        summary = run_once(session, settings)
        session.commit()

    print(f"cohorts_evaluated={summary.cohorts_evaluated} fired={summary.fired}")
    for cohort in summary.fired_cohorts:
        print(f"  ALERT: {cohort}")
    for reason, count in summary.suppressed_reasons.items():
        print(f"  suppressed[{reason}]={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
