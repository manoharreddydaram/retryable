"""The baseline tracker: an exponentially weighted moving average of a
cohort's own recent rate, so "normal" is whatever this cohort has actually
been doing lately rather than a fixed historical constant that never
adapts. Deliberately separate from significance.py's test -- this module
only ever answers "what should we currently expect," never "is this
observation surprising."
"""

_NO_PRIOR = None


def update_ewma(prior_rate: float | None, observed_rate: float, alpha: float) -> float:
    """The first observation for a cohort has nothing to blend against and
    becomes the baseline outright (bootstrap) -- see
    src/detect/service.py's insufficient_history handling, which is what
    stops that bootstrap run from being scored against itself."""
    if prior_rate is _NO_PRIOR:
        return observed_rate
    return alpha * observed_rate + (1 - alpha) * prior_rate
