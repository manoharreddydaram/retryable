"""Deterministic classification: Razorpay error_reason -> FailureCategory.

No AI anywhere in this file, by design (see the AI-usage boundary in
README.md) -- this is a lookup, and a lookup is free, instant, and 100%
reproducible in a way a model call never is. An error_reason this project
has never seen falls through to UNKNOWN, which is where Stage 7's long-tail
classifier picks up.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from src.classify.taxonomy import FailureCategory

_TAXONOMY_PATH = Path(__file__).parent / "error_taxonomy.yaml"


@dataclass(frozen=True)
class CategoryProfile:
    recoverable: bool
    customer_actionable: bool
    retry_timing: str
    description: str


@dataclass(frozen=True)
class ClassificationResult:
    category: FailureCategory
    profile: CategoryProfile
    matched_on: str  # "error_reason" | "error_code" | "no_match"
    matched_value: str | None
    confidence: float


# An exact error_reason match is a direct lookup: full confidence. A bare
# error_code fallback (GATEWAY_ERROR, SERVER_ERROR) is coarser -- still
# fairly reliable, but not as specific -- so it's set just above the policy
# engine's default confidence floor (0.7), not at 1.0. No match at all is
# honestly 0.0: the confidence floor gate exists precisely so "we don't
# know" is never silently treated as "we're sure."
_CONFIDENCE_BY_MATCH = {"error_reason": 1.0, "error_code": 0.85, "no_match": 0.0}


@lru_cache
def load_taxonomy() -> dict:
    with _TAXONOMY_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@lru_cache
def category_profiles() -> dict[FailureCategory, CategoryProfile]:
    raw = load_taxonomy()["categories"]
    return {
        FailureCategory(name): CategoryProfile(
            recoverable=spec["recoverable"],
            customer_actionable=spec["customer_actionable"],
            retry_timing=spec["retry_timing"],
            description=spec["description"].strip(),
        )
        for name, spec in raw.items()
    }


def classify(error_reason: str | None, error_code: str | None = None) -> ClassificationResult:
    taxonomy = load_taxonomy()
    profiles = category_profiles()

    if error_reason and error_reason in taxonomy["error_reasons"]:
        category = FailureCategory(taxonomy["error_reasons"][error_reason])
        return ClassificationResult(
            category,
            profiles[category],
            "error_reason",
            error_reason,
            _CONFIDENCE_BY_MATCH["error_reason"],
        )

    if error_code and error_code in taxonomy["error_codes"]:
        category = FailureCategory(taxonomy["error_codes"][error_code])
        return ClassificationResult(
            category,
            profiles[category],
            "error_code",
            error_code,
            _CONFIDENCE_BY_MATCH["error_code"],
        )

    return ClassificationResult(
        FailureCategory.UNKNOWN,
        profiles[FailureCategory.UNKNOWN],
        "no_match",
        None,
        _CONFIDENCE_BY_MATCH["no_match"],
    )
