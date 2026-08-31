"""Loads, hashes, and renders the versioned diagnosis prompt template.

prompt_hash identifies which version of prompts/diagnose_v1.md produced a
diagnosis -- computed from the raw template file with its placeholders
unrendered, so it stays a stable "which prompt-engineering version" marker
rather than changing on every call just because the evidence differs.

The taxonomy and catalog descriptions are rendered in from
error_taxonomy.yaml / interventions.yaml at call time, not copied into the
template by hand, so the prompt can never describe a category or
intervention differently than the rest of the system does.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from src.classify.rules import category_profiles
from src.diagnose.evidence import EvidenceBundle
from src.policy.catalog import intervention_profiles

PROMPT_VERSION = "diagnose_v1"
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "diagnose_v1.md"


@lru_cache
def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


@lru_cache
def prompt_hash() -> str:
    return hashlib.sha256(_template().encode("utf-8")).hexdigest()


def _categories_block() -> str:
    return "\n".join(
        f"- {category.value}: {profile.description}"
        for category, profile in category_profiles().items()
    )


def _interventions_block() -> str:
    return "\n".join(
        f"- {name.value}: {profile.description}"
        for name, profile in intervention_profiles().items()
    )


def render_prompt(bundle: EvidenceBundle) -> str:
    return _template().format(
        categories_block=_categories_block(),
        interventions_block=_interventions_block(),
        evidence_block=bundle.render(),
    )
