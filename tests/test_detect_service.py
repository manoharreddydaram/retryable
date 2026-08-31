"""Tests for evaluate_cohort(), the Stage 8 orchestrator. Uses a real
Postgres session (see conftest.py) for the persisted baseline/run rows, but
constructs CohortStats directly rather than seeding payments through
cohorts.py -- this module doesn't care where its input came from, only
what it does with it.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.detect.cohorts import CohortStats
from src.detect.models import DetectorBaseline
from src.detect.service import evaluate_cohort
from src.ledger.models import LedgerEntry
from tests.conftest import make_settings

_NOW = datetime(2026, 6, 16, 14, 0, tzinfo=UTC)
_WINDOW_START = _NOW - timedelta(hours=1)
_LATER = _NOW + timedelta(hours=1)


def _settings(**overrides):
    return make_settings(
        detector_min_sample_size=20,
        detector_confidence_threshold=0.99,
        detector_ewma_alpha=0.3,
        detector_baseline_strength=50.0,
        **overrides,
    )


def test_below_minimum_sample_is_suppressed_without_touching_the_baseline(db_session) -> None:
    stats = CohortStats(cohort="stage8:tiny", observed_count=2, total_count=3)

    result = evaluate_cohort(db_session, stats, _settings(), _WINDOW_START, _NOW)

    assert result.fired is False
    assert result.run.suppressed_reason == "insufficient_sample"
    assert result.run.probability_degraded is None
    assert db_session.get(DetectorBaseline, "stage8:tiny") is None


def test_first_sufficient_sample_bootstraps_the_baseline(db_session) -> None:
    stats = CohortStats(cohort="stage8:fresh", observed_count=5, total_count=25)

    result = evaluate_cohort(db_session, stats, _settings(), _WINDOW_START, _NOW)

    assert result.fired is False
    assert result.run.suppressed_reason == "insufficient_history"
    assert result.run.probability_degraded is None

    baseline = db_session.get(DetectorBaseline, "stage8:fresh")
    assert baseline.ewma_rate == 5 / 25
    assert baseline.observations == 1


def test_steady_rate_against_its_own_baseline_is_not_significant(db_session) -> None:
    cohort = "stage8:steady"
    settings = _settings()
    evaluate_cohort(
        db_session, CohortStats(cohort, 10, 100), settings, _WINDOW_START, _NOW
    )  # bootstrap at 10%

    result = evaluate_cohort(
        db_session, CohortStats(cohort, 3, 30), settings, _NOW, _LATER
    )  # still ~10%

    assert result.fired is False
    assert result.run.suppressed_reason == "not_significant"
    assert result.run.probability_degraded is not None
    assert result.run.probability_degraded < settings.detector_confidence_threshold


def test_a_real_spike_fires_and_is_logged_to_the_ledger(db_session) -> None:
    cohort = "stage8:outage"
    settings = _settings()
    evaluate_cohort(
        db_session, CohortStats(cohort, 10, 100), settings, _WINDOW_START, _NOW
    )  # bootstrap at 10%

    result = evaluate_cohort(
        db_session, CohortStats(cohort, 18, 40), settings, _NOW, _LATER
    )  # 45% observed

    assert result.fired is True
    assert result.run.suppressed_reason is None
    assert result.run.probability_degraded > settings.detector_confidence_threshold

    ledger_entry = db_session.execute(
        select(LedgerEntry).where(
            LedgerEntry.entity_type == "cohort",
            LedgerEntry.entity_id == cohort,
            LedgerEntry.event_type == "degradation.alert_fired",
        )
    ).scalar_one()
    assert ledger_entry.payload["probability_degraded"] > settings.detector_confidence_threshold


def test_suppressed_run_is_never_logged_to_the_ledger(db_session) -> None:
    cohort = "stage8:quiet"
    settings = _settings()
    evaluate_cohort(db_session, CohortStats(cohort, 10, 100), settings, _WINDOW_START, _NOW)

    evaluate_cohort(db_session, CohortStats(cohort, 3, 30), settings, _NOW, _LATER)

    entries = db_session.execute(
        select(LedgerEntry).where(
            LedgerEntry.entity_type == "cohort", LedgerEntry.entity_id == cohort
        )
    ).all()
    assert entries == []


def test_the_test_runs_against_the_baseline_before_this_windows_update(db_session) -> None:
    """The probability_degraded computed for a run, and the baseline_rate
    recorded on it, must both reflect the baseline as it stood BEFORE this
    window's observation was blended in -- otherwise a cohort would always
    be judged against a baseline partly made of the very data being judged."""
    cohort = "stage8:advancing"
    settings = _settings()
    evaluate_cohort(
        db_session, CohortStats(cohort, 10, 100), settings, _WINDOW_START, _NOW
    )  # bootstrap at 10%

    result = evaluate_cohort(
        db_session, CohortStats(cohort, 20, 100), settings, _NOW, _LATER
    )  # 20% observed

    assert result.run.baseline_rate == 0.10

    baseline = db_session.get(DetectorBaseline, cohort)
    assert baseline.ewma_rate == 0.3 * 0.20 + 0.7 * 0.10
    assert baseline.observations == 2
