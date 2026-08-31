"""Pure tests for the payer-response simulator. No database."""

from eval.payer_simulator import probability_of_conversion, simulate_conversion


def test_known_category_returns_its_documented_immediate_probability() -> None:
    assert probability_of_conversion("insufficient_funds", "immediate") == 0.35


def test_delayed_auth_abandoned_is_lower_than_immediate() -> None:
    immediate = probability_of_conversion("auth_abandoned", "immediate")
    delayed = probability_of_conversion("auth_abandoned", "delayed_1h")
    assert delayed < immediate


def test_delayed_insufficient_funds_is_unchanged() -> None:
    immediate = probability_of_conversion("insufficient_funds", "immediate")
    delayed = probability_of_conversion("insufficient_funds", "delayed_1h")
    assert delayed == immediate


def test_unrecoverable_categories_have_low_propensity() -> None:
    assert probability_of_conversion("instrument_blocked", "immediate") < 0.10
    assert probability_of_conversion("merchant_config_error", "immediate") < 0.10


def test_simulate_conversion_is_deterministic() -> None:
    first = simulate_conversion("insufficient_funds", "immediate", seed=1, order_id="order_1")
    second = simulate_conversion("insufficient_funds", "immediate", seed=1, order_id="order_1")
    assert first == second


def test_simulate_conversion_varies_by_order() -> None:
    results = {
        simulate_conversion("insufficient_funds", "immediate", seed=1, order_id=f"order_{i}")
        for i in range(50)
    }
    assert results == {True, False}


def test_conversion_rate_over_many_draws_is_close_to_the_configured_probability() -> None:
    conversions = sum(
        simulate_conversion("input_error_retriable", "immediate", seed=1, order_id=f"order_{i}")
        for i in range(2000)
    )
    rate = conversions / 2000
    assert abs(rate - 0.50) < 0.05
