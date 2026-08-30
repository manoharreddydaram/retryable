"""Runs the outbox dispatcher once: claims eligible pending entries and
executes them against Razorpay. Meant to be invoked repeatedly (manually,
or on a schedule) rather than run as a long-lived daemon -- see
src/execute/dispatcher.py's run_once() docstring for why a poll-based
design was chosen.

Usage:
    python scripts/run_dispatcher.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.db.base import SessionLocal  # noqa: E402
from src.execute.dispatcher import run_once  # noqa: E402
from src.execute.razorpay_client import RazorpayClient  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        print("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set in .env -- nothing to dispatch.")
        return 1

    client = RazorpayClient(settings.razorpay_key_id, settings.razorpay_key_secret)

    with SessionLocal() as session:
        summary = run_once(session, client, settings)
        session.commit()

    print(
        f"claimed={summary.claimed} completed={summary.completed} recovered={summary.recovered} "
        f"failed={summary.failed} failed_permanently={summary.failed_permanently} "
        f"skipped_breaker_open={summary.skipped_breaker_open}"
    )
    for error in summary.errors:
        print(f"  error: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
