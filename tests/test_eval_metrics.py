"""Pure tests for the confidence-interval helper. The rest of eval/metrics.py
is exercised end to end, against a real database, in test_run_eval.py.
"""

from eval.metrics import two_proportion_ci95


def test_identical_proportions_give_a_ci_centered_on_zero() -> None:
    lo, hi = two_proportion_ci95(0.3, 100, 0.3, 100)
    assert lo < 0 < hi
    assert abs((lo + hi) / 2) < 1e-9


def test_wide_enough_gap_excludes_zero_with_enough_samples() -> None:
    lo, _ = two_proportion_ci95(0.5, 1000, 0.1, 1000)
    assert lo > 0


def test_zero_sample_size_returns_a_degenerate_interval() -> None:
    assert two_proportion_ci95(0.5, 0, 0.1, 100) == (0.0, 0.0)


def test_interval_widens_with_smaller_sample_sizes() -> None:
    _, hi_small = two_proportion_ci95(0.3, 10, 0.3, 10)
    _, hi_large = two_proportion_ci95(0.3, 1000, 0.3, 1000)
    assert hi_small > hi_large
