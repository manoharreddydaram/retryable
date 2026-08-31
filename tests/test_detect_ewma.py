"""Pure tests for the EWMA baseline update. No database."""

import pytest

from src.detect.ewma import update_ewma


def test_first_observation_bootstraps_the_baseline_outright() -> None:
    assert update_ewma(None, observed_rate=0.42, alpha=0.3) == 0.42


def test_blends_toward_the_new_observation_by_alpha() -> None:
    new_rate = update_ewma(prior_rate=0.10, observed_rate=0.50, alpha=0.3)
    assert new_rate == pytest.approx(0.3 * 0.50 + 0.7 * 0.10)


def test_alpha_zero_never_moves_the_baseline() -> None:
    assert update_ewma(prior_rate=0.20, observed_rate=0.90, alpha=0.0) == 0.20


def test_alpha_one_replaces_the_baseline_outright() -> None:
    assert update_ewma(prior_rate=0.20, observed_rate=0.90, alpha=1.0) == 0.90
