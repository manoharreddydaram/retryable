"""category -> default proposal. See policies/rules.yaml.

This is Stage 4's own proposer, used until Stage 7's LLM exists. Its output
is a Proposal like any other -- it still passes through every gate in
engine.py and has no special authority.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from src.classify.taxonomy import FailureCategory
from src.policy.catalog import Intervention

_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "policies" / "rules.yaml"


@dataclass(frozen=True)
class CategoryRule:
    intervention: Intervention
    wait_hours: float | None
    description: str


@lru_cache
def load_category_rules() -> dict[FailureCategory, CategoryRule]:
    with _RULES_PATH.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)["category_rules"]
    return {
        FailureCategory(name): CategoryRule(
            intervention=Intervention(spec["intervention"]),
            wait_hours=spec.get("wait_hours"),
            description=spec["description"].strip(),
        )
        for name, spec in raw.items()
    }


def propose_default(category: FailureCategory) -> Intervention:
    return load_category_rules()[category].intervention
