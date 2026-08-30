"""Data-integrity tests for the intervention catalog and category rules.

Two of these tests (unrecoverable -> suppress, non-actionable -> no contact)
cross-check policies/rules.yaml against src/classify/error_taxonomy.yaml
automatically, so a rule authored inconsistently with the taxonomy fails
here instead of surfacing as a bad decision in production.
"""

from src.classify.rules import category_profiles
from src.classify.taxonomy import FailureCategory
from src.policy.catalog import (
    Intervention,
    intervention_profiles,
    load_catalog,
    resolve_intervention,
)
from src.policy.rules_table import load_category_rules
from src.policy.stopping_rules import stopping_rule_reasons


def test_catalog_enum_matches_yaml() -> None:
    yaml_names = set(load_catalog()["interventions"].keys())
    enum_names = {i.value for i in Intervention}
    assert yaml_names == enum_names


def test_every_intervention_has_a_profile() -> None:
    assert set(intervention_profiles().keys()) == set(Intervention)


def test_resolve_intervention_recognizes_real_names() -> None:
    assert resolve_intervention("send_payment_link") == Intervention.SEND_PAYMENT_LINK


def test_resolve_intervention_rejects_unknown_names() -> None:
    assert resolve_intervention("give_a_discount") is None


def test_every_failure_category_has_a_rule() -> None:
    assert set(load_category_rules().keys()) == set(FailureCategory)


def test_unrecoverable_categories_default_to_suppress() -> None:
    """UNKNOWN is deliberately excluded: it's marked unrecoverable because we
    have no evidence either way, not because we're confident it's dead --
    "don't know" and "know it can't work" call for different defaults
    (escalate_to_human vs. suppress). In practice UNKNOWN's confidence is
    0.0, so LOW_CONFIDENCE catches it before this rule would ever apply."""
    profiles = category_profiles()
    rules = load_category_rules()
    for category, profile in profiles.items():
        if category == FailureCategory.UNKNOWN:
            continue
        if not profile.recoverable:
            assert rules[category].intervention == Intervention.SUPPRESS, category


def test_non_customer_actionable_categories_never_default_to_contact() -> None:
    profiles = category_profiles()
    rules = load_category_rules()
    profiles_by_intervention = intervention_profiles()
    for category, profile in profiles.items():
        if not profile.customer_actionable:
            default = rules[category].intervention
            assert not profiles_by_intervention[default].requires_customer_contact, category


def test_stopping_rules_yaml_has_a_reason_for_every_rule_id_the_engine_uses() -> None:
    reasons = stopping_rule_reasons()
    expected = {
        "KILL_SWITCH",
        "LOW_CONFIDENCE",
        "UNRECOVERABLE_CATEGORY",
        "TOUCH_CAP_EXCEEDED",
        "HUMAN_APPROVAL_REQUIRED",
        "BATCH_INTERVENTION_CEILING",
        "OUT_OF_CATALOG",
        "CATEGORY_NOT_CUSTOMER_ACTIONABLE",
        "QUIET_HOURS",
    }
    assert expected.issubset(reasons.keys())
