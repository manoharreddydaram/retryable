"""Rule IDs and human-readable reasons for every gate the policy engine can
stop a proposal on. See policies/stopping_rules.yaml -- the numeric
thresholds themselves live in Settings (src/config.py), declared since
Stage 0.
"""

from functools import lru_cache
from pathlib import Path

import yaml

_STOPPING_RULES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "policies" / "stopping_rules.yaml"
)


@lru_cache
def stopping_rule_reasons() -> dict[str, str]:
    with _STOPPING_RULES_PATH.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)["gates"]
    return {gate["rule_id"]: gate["description"].strip() for gate in raw}
