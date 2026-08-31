"""Simulates whether a customer converts, given only (category, timing).

Blind to which arm triggered the send, which rule authorised it, which
intervention text was drafted, or any confidence score -- exactly the
discipline EVALUATION.md commits to, so this simulator cannot be tuned,
even unconsciously, to flatter our own decisions. It can only reward
putting the right cohort into the right timing, which is the thing under
test.
"""

import random
from functools import lru_cache
from pathlib import Path

import yaml

_PROPENSITIES_PATH = Path(__file__).parent / "propensities.yaml"


@lru_cache
def load_propensities() -> dict:
    with _PROPENSITIES_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def probability_of_conversion(category: str, timing: str) -> float:
    data = load_propensities()
    base = data["immediate"].get(category, data["immediate"]["unknown"])
    if timing == "delayed_1h":
        multiplier = data["delayed_1h_multiplier"].get(
            category, data["delayed_1h_multiplier"]["default"]
        )
        return base * multiplier
    return base


def simulate_conversion(category: str, timing: str, seed: int, order_id: str) -> bool:
    """order_id makes the draw independent per order while staying fully
    reproducible: the same (seed, order_id) always yields the same result."""
    rng = random.Random(f"{seed}-{order_id}")
    return rng.random() < probability_of_conversion(category, timing)
