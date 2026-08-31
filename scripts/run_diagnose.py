"""Runs the diagnosis pass once: finds every order the deterministic
classifier could not resolve, sends each to Claude for a long-tail
diagnosis, and runs any confident, citation-valid result through the same
policy engine as every other proposal. Meant to be invoked repeatedly
(manually, or on a schedule) -- see src/diagnose/runner.py's run_once() for
why a poll-based design was chosen, mirroring run_dispatcher.py.

Usage:
    python scripts/run_diagnose.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.db.base import SessionLocal  # noqa: E402
from src.diagnose.runner import run_once  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set in .env -- nothing to diagnose.")
        return 1

    with SessionLocal() as session:
        summary = run_once(session, settings)
        session.commit()

    print(
        f"considered={summary.considered} succeeded={summary.succeeded} "
        f"upgraded={summary.upgraded} failed={summary.failed}"
    )
    for reason, count in summary.failure_reasons.items():
        print(f"  failed[{reason}]={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
