"""Tests for the cohort statistics queries, against a real Postgres
instance (see conftest.py). Uses a window far enough in the future that no
other test or real dev activity could ever have touched it, so counts
start clean without needing a baseline-delta pattern -- unlike
test_diagnose_runner.py, these query functions take their window as an
explicit argument rather than defaulting to "now".
"""

from datetime import UTC, datetime, timedelta

from src.detect.cohorts import category_share_stats, overall_stats
from src.ingest.models import Payment

_WINDOW_END = datetime(2031, 3, 1, tzinfo=UTC)
_WINDOW_START = _WINDOW_END - timedelta(hours=1)
_INSIDE = _WINDOW_START + timedelta(minutes=1)


def _seed_payment(
    session, order_id: str, *, status: str, category: str | None = None, when: datetime = _INSIDE
) -> None:
    session.add(
        Payment(
            order_id=order_id,
            status=status,
            latest_payment_id=f"pay_{order_id}",
            amount_paise=10_000,
            currency="INR",
            method="card",
            category=category,
            raw_payload={},
            created_at=when,
            updated_at=when,
        )
    )
    session.flush()


def test_overall_stats_counts_failed_and_captured(db_session) -> None:
    _seed_payment(db_session, "stage8_order_f1", status="failed")
    _seed_payment(db_session, "stage8_order_f2", status="failed")
    _seed_payment(db_session, "stage8_order_c1", status="captured")

    stats = overall_stats(db_session, _WINDOW_START, _WINDOW_END)

    assert stats.cohort == "overall"
    assert stats.observed_count == 2
    assert stats.total_count == 3


def test_overall_stats_excludes_payments_outside_the_window(db_session) -> None:
    _seed_payment(
        db_session, "stage8_order_outside", status="failed", when=_WINDOW_START - timedelta(hours=5)
    )

    stats = overall_stats(db_session, _WINDOW_START, _WINDOW_END)
    assert stats.total_count == 0


def test_category_share_stats_covers_every_taxonomy_category_even_at_zero(db_session) -> None:
    stats = category_share_stats(db_session, _WINDOW_START, _WINDOW_END)
    cohorts = {s.cohort for s in stats}

    assert "category_share:insufficient_funds" in cohorts
    assert "category_share:infra_outage" in cohorts
    assert "category_share:unknown" in cohorts
    assert all(s.observed_count == 0 and s.total_count == 0 for s in stats)


def test_category_share_stats_computes_share_of_failures_not_share_of_attempts(db_session) -> None:
    _seed_payment(db_session, "stage8_outage_1", status="failed", category="infra_outage")
    _seed_payment(db_session, "stage8_outage_2", status="failed", category="infra_outage")
    _seed_payment(db_session, "stage8_funds_1", status="failed", category="insufficient_funds")
    _seed_payment(
        db_session, "stage8_captured", status="captured"
    )  # never counted -- not a failure

    stats = {s.cohort: s for s in category_share_stats(db_session, _WINDOW_START, _WINDOW_END)}

    outage = stats["category_share:infra_outage"]
    assert outage.observed_count == 2
    assert outage.total_count == 3  # total FAILURES in the window, not total attempts

    funds = stats["category_share:insufficient_funds"]
    assert funds.observed_count == 1
    assert funds.total_count == 3
