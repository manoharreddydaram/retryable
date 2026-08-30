"""The closed intervention catalog. See policies/interventions.yaml.

A proposal naming anything outside this catalog is rejected by the policy
engine, not merely discouraged -- see decide() in engine.py.
"""

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml

_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "policies" / "interventions.yaml"


class Intervention(StrEnum):
    SEND_PAYMENT_LINK = "send_payment_link"
    WAIT = "wait"
    VERIFY_STATUS = "verify_status"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    SUPPRESS = "suppress"


@dataclass(frozen=True)
class InterventionProfile:
    requires_customer_contact: bool
    calls_razorpay: bool
    description: str


@lru_cache
def load_catalog() -> dict:
    with _CATALOG_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@lru_cache
def intervention_profiles() -> dict[Intervention, InterventionProfile]:
    raw = load_catalog()["interventions"]
    return {
        Intervention(name): InterventionProfile(
            requires_customer_contact=spec["requires_customer_contact"],
            calls_razorpay=spec["calls_razorpay"],
            description=spec["description"].strip(),
        )
        for name, spec in raw.items()
    }


def resolve_intervention(name: str) -> Intervention | None:
    """None (not an exception) for a name outside the catalog -- the caller
    (the policy engine) decides what an out-of-catalog proposal means; this
    function's only job is to say whether the name is real."""
    try:
        return Intervention(name)
    except ValueError:
        return None
