"""Tests for run_once(), the Stage 8 batch entrypoint that mirrors
src/execute/dispatcher.py and src/diagnose/runner.py's shape.

now is always passed explicitly and pinned far in the future, so each
test's window is guaranteed empty of unrelated data -- the same reasoning
as test_detect_cohorts.py, extended to the runner level.
"""

from datetime import UTC, datetime, timedelta

from src.detect.models import DetectorBaseline
from src.detect.runner import run_once
from src.ingest.models import Payment
from tests.conftest import make_settings

_NOW = datetime(2031, 4, 1, tzinfo=UTC)


def _settings(**overrides):
    return make_settings(
        detector_window_minutes=60,
        detector_min_sample_size=20,
        detector_confidence_threshold=0.99,
        detector_ewma_alpha=0.3,
        detector_baseline_strength=50.0,
        **overrides,
    )


def _seed_payment(
    session, order_id: str, *, status: str, category: str | None = None, when: datetime
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


def test_run_once_evaluates_overall_plus_every_taxonomy_category(db_session) -> None:
    summary = run_once(db_session, _settings(), now=_NOW)
    assert summary.cohorts_evaluated == 10  # 1 overall + 9 categories


def test_run_once_suppresses_everything_below_the_sample_floor(db_session) -> None:
    for i in range(5):
        _seed_payment(
            db_session,
            f"stage8_runner_small_{i}",
            status="failed",
            when=_NOW - timedelta(minutes=1),
        )

    summary = run_once(db_session, _settings(), now=_NOW)

    assert summary.fired == 0
    assert summary.suppressed_reasons.get("insufficient_sample", 0) == 10


def test_run_once_bootstraps_every_cohort_on_first_sufficient_run(db_session) -> None:
    when = _NOW - timedelta(minutes=1)
    for i in range(20):
        _seed_payment(
            db_session,
            f"stage8_runner_fail_{i}",
            status="failed",
            category="insufficient_funds",
            when=when,
        )
    for i in range(5):
        _seed_payment(db_session, f"stage8_runner_ok_{i}", status="captured", when=when)

    summary = run_once(db_session, _settings(), now=_NOW)

    assert summary.fired == 0
    assert summary.suppressed_reasons.get("insufficient_history", 0) == 10
    assert db_session.get(DetectorBaseline, "overall") is not None
    assert db_session.get(DetectorBaseline, "category_share:insufficient_funds") is not None


def test_run_once_reports_which_cohort_fired_and_leaves_the_rest_alone(db_session) -> None:
    settings = _settings()
    bootstrap_time = _NOW - timedelta(minutes=1)
    for i in range(18):
        _seed_payment(
            db_session,
            f"stage8_runner_bootstrap_funds_{i}",
            status="failed",
            category="insufficient_funds",
            when=bootstrap_time,
        )
    for i in range(2):
        _seed_payment(
            db_session,
            f"stage8_runner_bootstrap_outage_{i}",
            status="failed",
            category="infra_outage",
            when=bootstrap_time,
        )
    for i in range(20):
        _seed_payment(
            db_session, f"stage8_runner_bootstrap_ok_{i}", status="captured", when=bootstrap_time
        )
    run_once(
        db_session, settings, now=_NOW
    )  # bootstraps: infra_outage share=10%, insufficient_funds share=90%

    later = _NOW + timedelta(hours=1)
    spike_time = later - timedelta(minutes=1)
    for i in range(18):
        _seed_payment(
            db_session,
            f"stage8_runner_spike_outage_{i}",
            status="failed",
            category="infra_outage",
            when=spike_time,
        )
    for i in range(2):
        _seed_payment(
            db_session,
            f"stage8_runner_spike_funds_{i}",
            status="failed",
            category="insufficient_funds",
            when=spike_time,
        )
    for i in range(20):
        # Keeps the *overall* failure rate at the same ~50% as the
        # bootstrap window, so this scenario isolates one signal: a shift
        # in which category is responsible for failures, not a change in
        # how often payments fail at all.
        _seed_payment(db_session, f"stage8_runner_spike_ok_{i}", status="captured", when=spike_time)

    summary = run_once(db_session, settings, now=later)

    assert summary.fired_cohorts == ["category_share:infra_outage"]
