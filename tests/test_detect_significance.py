"""Pure tests for the beta-binomial significance test. No database --
these are just numbers in, a probability out."""

import pytest

from src.detect.significance import clip_rate, probability_degraded


def test_matching_rates_are_inconclusive() -> None:
    """Not required to land at exactly 0.5: the baseline is modeled as a
    pure scaled rate while the recent window carries its own flat Beta(1, 1)
    prior, so a small-sample correction nudges an exact-rate match slightly
    above 0.5. What matters is that it's nowhere near the firing threshold
    in either direction."""
    p = probability_degraded(
        baseline_rate=0.10, baseline_strength=100, observed_count=10, total_count=100
    )
    assert 0.3 < p < 0.8


def test_clearly_worse_recent_rate_is_confidently_flagged() -> None:
    p = probability_degraded(
        baseline_rate=0.10, baseline_strength=100, observed_count=18, total_count=40
    )
    assert p > 0.999


def test_clearly_better_recent_rate_is_not_flagged() -> None:
    p = probability_degraded(
        baseline_rate=0.30, baseline_strength=100, observed_count=2, total_count=40
    )
    assert p < 0.01


def test_zero_total_count_is_never_flagged_as_degraded() -> None:
    p = probability_degraded(
        baseline_rate=0.10, baseline_strength=100, observed_count=0, total_count=0
    )
    assert p == 0.0


def test_tiny_sample_alone_is_not_a_safe_gate() -> None:
    """Demonstrates exactly why service.py enforces a hard minimum-sample
    count BEFORE this test ever runs (designed failure #4, CLAUDE.md): with
    an uninformative Beta(1, 1) prior on the recent side, 2 failures out of
    3 attempts alone produces high confidence against an established
    baseline, even though n=3 obviously isn't enough evidence to act on.
    The significance test is honest about the (thin) evidence it was given
    -- it isn't told n=3 is too small to trust, because on its own terms it
    isn't wrong, it just wasn't asked the right question. That's the gate's
    job, not this function's."""
    p = probability_degraded(
        baseline_rate=0.10, baseline_strength=100, observed_count=2, total_count=3
    )
    assert p > 0.95


@pytest.mark.parametrize("rate", [0.0, 1.0])
def test_clip_rate_keeps_beta_parameters_strictly_positive(rate: float) -> None:
    clipped = clip_rate(rate)
    assert 0.0 < clipped < 1.0


def test_clip_rate_leaves_ordinary_rates_untouched() -> None:
    assert clip_rate(0.42) == 0.42
