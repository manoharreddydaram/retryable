"""Data-integrity and classification tests for the Stage 3 taxonomy.

No AI anywhere here -- this is a pure lookup table, tested the same way
you'd test any other deterministic function.
"""

from src.classify.rules import category_profiles, classify, load_taxonomy
from src.classify.taxonomy import FailureCategory


def test_failure_category_enum_matches_yaml_categories() -> None:
    yaml_categories = set(load_taxonomy()["categories"].keys())
    enum_categories = {c.value for c in FailureCategory}
    assert yaml_categories == enum_categories


def test_every_mapped_error_reason_points_at_a_real_category() -> None:
    taxonomy = load_taxonomy()
    valid = set(taxonomy["categories"].keys())
    for reason, category in taxonomy["error_reasons"].items():
        assert category in valid, f"{reason} -> unknown category {category!r}"


def test_every_mapped_error_code_points_at_a_real_category() -> None:
    taxonomy = load_taxonomy()
    valid = set(taxonomy["categories"].keys())
    for code, category in taxonomy["error_codes"].items():
        assert category in valid, f"{code} -> unknown category {category!r}"


def test_taxonomy_covers_all_109_documented_error_reasons() -> None:
    assert len(load_taxonomy()["error_reasons"]) == 109


def test_every_category_has_a_profile() -> None:
    assert set(category_profiles().keys()) == set(FailureCategory)


def test_insufficient_funds_is_recoverable_but_delayed() -> None:
    result = classify("insufficient_funds")
    assert result.category == FailureCategory.INSUFFICIENT_FUNDS
    assert result.profile.recoverable is True
    assert result.profile.retry_timing == "delayed"


def test_card_expired_is_not_recoverable_via_retry() -> None:
    result = classify("card_expired")
    assert result.category == FailureCategory.INSTRUMENT_BLOCKED
    assert result.profile.recoverable is False


def test_gateway_timeout_requires_verification_before_acting() -> None:
    result = classify("payment_timed_out")
    assert result.category == FailureCategory.AMBIGUOUS_VERIFY_BEFORE_ACTING
    assert result.profile.retry_timing == "verify_before_acting"


def test_order_already_paid_requires_verification_before_acting() -> None:
    result = classify("order_already_paid")
    assert result.category == FailureCategory.AMBIGUOUS_VERIFY_BEFORE_ACTING


def test_bank_outage_is_recoverable_but_not_customer_actionable() -> None:
    result = classify("bank_not_available")
    assert result.category == FailureCategory.INFRA_OUTAGE
    assert result.profile.recoverable is True
    assert result.profile.customer_actionable is False


def test_merchant_config_error_is_never_customer_facing() -> None:
    result = classify("invalid_order_id")
    assert result.category == FailureCategory.MERCHANT_CONFIG_ERROR
    assert result.profile.customer_actionable is False


def test_unrecognized_reason_falls_back_to_unknown() -> None:
    result = classify("some_reason_razorpay_has_never_documented")
    assert result.category == FailureCategory.UNKNOWN
    assert result.matched_on == "no_match"


def test_error_code_is_used_only_when_reason_is_missing() -> None:
    result = classify(None, "GATEWAY_ERROR")
    assert result.category == FailureCategory.INFRA_OUTAGE
    assert result.matched_on == "error_code"


def test_reason_takes_priority_over_code() -> None:
    result = classify("insufficient_funds", "GATEWAY_ERROR")
    assert result.category == FailureCategory.INSUFFICIENT_FUNDS
    assert result.matched_on == "error_reason"


def test_no_signal_at_all_falls_back_to_unknown() -> None:
    assert classify(None, None).category == FailureCategory.UNKNOWN
