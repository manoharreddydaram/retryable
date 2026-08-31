"""The actual significance test: is a cohort's recent observed rate really
higher than its tracked baseline, or is this within normal noise?

Modeled as a beta-binomial comparison rather than a normal-approximation
z-test deliberately: the baseline is treated as a Beta distribution (its
EWMA rate, weighted by how many pseudo-observations we trust it to be worth
-- see ewma.py) and the recent window as a second Beta distribution (a
uniform prior updated by the window's real counts). The question "is the
recent rate higher" then has an exact answer, P(recent > baseline),
computed by integrating one posterior against the other's CDF -- no Monte
Carlo, no seed, no sampling noise. The same (baseline_rate,
baseline_strength, observed_count, total_count) always produces the same
probability, up to floating-point/quadrature precision.

This function alone is deliberately NOT trusted to prevent false alarms on
small samples -- see test_detect_significance.py's
test_tiny_sample_alone_is_not_a_safe_gate for a concrete demonstration that
it isn't. A hard minimum-sample count (src/detect/service.py) is a
required, separate safeguard, not a redundant one: with an uninformative
Beta(1, 1) prior on the recent side, a handful of unlucky observations can
push the posterior far enough to look confident even though there's no
real information behind it.
"""

from scipy import integrate, stats

_RATE_FLOOR = 1e-3  # keeps Beta shape parameters strictly positive at 0% or 100%


def clip_rate(rate: float) -> float:
    return min(max(rate, _RATE_FLOOR), 1 - _RATE_FLOOR)


def probability_degraded(
    baseline_rate: float,
    baseline_strength: float,
    observed_count: int,
    total_count: int,
) -> float:
    """P(the recent window's true rate > the baseline's true rate).

    baseline_rate/baseline_strength describe the baseline as a Beta
    distribution: strength is how many pseudo-observations of confidence
    the EWMA-tracked rate is worth (see Settings.detector_baseline_strength).
    The recent window uses a flat Beta(1, 1) prior updated by its own
    (observed_count, total_count) -- it earns its own confidence from real
    data, not from the baseline's.
    """
    if total_count <= 0:
        return 0.0

    baseline_rate = clip_rate(baseline_rate)
    baseline = stats.beta(
        baseline_rate * baseline_strength, (1 - baseline_rate) * baseline_strength
    )
    recent = stats.beta(1 + observed_count, 1 + (total_count - observed_count))

    probability, _abs_error = integrate.quad(lambda x: recent.pdf(x) * baseline.cdf(x), 0, 1)
    return min(max(probability, 0.0), 1.0)
