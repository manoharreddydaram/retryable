"""Razorpay client tests against a mocked HTTP transport -- no network call
and no real credentials needed. The critical scenario is the designed
failure: a create-payment-link call times out (outcome unknown), and a
retry with the *same* reference_id must recover cleanly whether or not the
first attempt actually reached Razorpay, because Razorpay enforces
reference_id uniqueness and rejects a second create with an explicit error
-- verified against their docs, not assumed.
"""

import httpx
import pytest

from src.execute.razorpay_client import RazorpayAPIError, RazorpayClient, RazorpayTimeoutError


def _client(handler) -> RazorpayClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://api.razorpay.com/v1", transport=transport)
    return RazorpayClient(key_id="rzp_test_fake", key_secret="fake_secret", http_client=http_client)


def test_create_payment_link_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payment_links"
        return httpx.Response(
            200, json={"id": "plink_1", "short_url": "https://rzp.io/l/abc", "status": "created"}
        )

    client = _client(handler)
    result = client.create_payment_link(
        reference_id="rtx-abc", amount_paise=50000, order_id="order_1"
    )

    assert result.id == "plink_1"
    assert result.recovered_from_conflict is False


def test_create_payment_link_recovers_from_a_duplicate_reference_id() -> None:
    """The designed failure: the first attempt actually succeeded, and a
    retry with the same reference_id hits Razorpay's real uniqueness
    constraint instead of creating a second link."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(
                400,
                json={"error": {"description": "payment link ref rtx-abc already exists"}},
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "plink_original",
                        "short_url": "https://rzp.io/l/original",
                        "status": "created",
                    }
                ]
            },
        )

    client = _client(handler)
    result = client.create_payment_link(
        reference_id="rtx-abc", amount_paise=50000, order_id="order_1"
    )

    assert result.id == "plink_original"
    assert result.recovered_from_conflict is True
    post_calls = [c for c in calls if c.method == "POST"]
    assert len(post_calls) == 1  # never retried the create itself -- recovered via fetch instead


def test_create_payment_link_raises_when_conflict_has_nothing_to_recover() -> None:
    """Shouldn't happen in practice, but must not silently fabricate a
    result if the reference_id error fires and the fetch finds nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                400, json={"error": {"description": "reference_id already exists"}}
            )
        return httpx.Response(200, json={"items": []})

    client = _client(handler)
    with pytest.raises(RazorpayAPIError):
        client.create_payment_link(reference_id="rtx-abc", amount_paise=50000, order_id="order_1")


def test_create_payment_link_raises_on_an_unrelated_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"description": "amount must be at least 100 paise"}}
        )

    client = _client(handler)
    with pytest.raises(RazorpayAPIError) as exc_info:
        client.create_payment_link(reference_id="rtx-abc", amount_paise=50, order_id="order_1")
    assert exc_info.value.status_code == 400


def test_timeout_is_reported_as_a_timeout_error_not_swallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    client = _client(handler)
    with pytest.raises(RazorpayTimeoutError):
        client.create_payment_link(reference_id="rtx-abc", amount_paise=50000, order_id="order_1")


def test_connect_error_is_retried_transparently() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise httpx.ConnectError("simulated blip", request=request)
        return httpx.Response(
            200, json={"id": "plink_1", "short_url": "https://rzp.io/l/abc", "status": "created"}
        )

    client = _client(handler)
    result = client.create_payment_link(
        reference_id="rtx-abc", amount_paise=50000, order_id="order_1"
    )

    assert result.id == "plink_1"
    assert attempts["count"] == 2


def test_fetch_by_reference_id_returns_none_when_nothing_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    client = _client(handler)
    assert client.fetch_by_reference_id("rtx-nope") is None


def test_get_payment_status_returns_the_real_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payments/pay_1"
        return httpx.Response(200, json={"id": "pay_1", "status": "captured"})

    client = _client(handler)
    assert client.get_payment_status("pay_1") == "captured"
