"""End-to-end tests through the real HTTP endpoint, signature check included.

The `client` fixture layers webhook-secret setup on top of conftest.py's
shared `api_client` fixture, which points the FastAPI app's DB dependency at
the same savepoint-backed session tests/conftest.py provides, so these
requests never touch data outside this test.
"""

import hashlib
import hmac
import json

import pytest

from src.config import get_settings

SECRET = "whsec_test_endpoint"


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _payload(event: str, payment_id: str, order_id: str, status: str) -> bytes:
    return json.dumps(
        {
            "entity": "event",
            "event": event,
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "amount": 50000,
                        "currency": "INR",
                        "status": status,
                        "order_id": order_id,
                        "method": "card",
                    }
                }
            },
            "created_at": 1700000000,
        }
    ).encode("utf-8")


@pytest.fixture()
def client(api_client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    yield api_client
    get_settings.cache_clear()


def test_valid_signature_is_accepted_and_applied(client) -> None:
    body = _payload("payment.failed", "pay_1", "order_1", "failed")
    response = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "X-Razorpay-Event-Id": "evt_1"},
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "applied"


def test_invalid_signature_is_rejected(client) -> None:
    body = _payload("payment.failed", "pay_1", "order_1", "failed")
    response = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "not-the-right-signature", "X-Razorpay-Event-Id": "evt_1"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_signature"


def test_missing_event_id_header_is_rejected(client) -> None:
    body = _payload("payment.failed", "pay_1", "order_1", "failed")
    response = client.post(
        "/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": _sign(body)}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "missing_event_id_header"


def test_duplicate_delivery_is_ignored_the_second_time(client) -> None:
    body = _payload("payment.failed", "pay_1", "order_1", "failed")
    headers = {"X-Razorpay-Signature": _sign(body), "X-Razorpay-Event-Id": "evt_1"}

    first = client.post("/webhooks/razorpay", content=body, headers=headers)
    second = client.post("/webhooks/razorpay", content=body, headers=headers)

    assert first.json()["outcome"] == "applied"
    assert second.json()["outcome"] == "duplicate_ignored"


def test_late_captured_recovers_a_failed_order_over_http(client) -> None:
    failed_body = _payload("payment.failed", "pay_1", "order_1", "failed")
    client.post(
        "/webhooks/razorpay",
        content=failed_body,
        headers={"X-Razorpay-Signature": _sign(failed_body), "X-Razorpay-Event-Id": "evt_1"},
    )

    captured_body = _payload("payment.captured", "pay_2", "order_1", "captured")
    response = client.post(
        "/webhooks/razorpay",
        content=captured_body,
        headers={"X-Razorpay-Signature": _sign(captured_body), "X-Razorpay-Event-Id": "evt_2"},
    )

    assert response.json()["outcome"] == "recovered"


def test_late_failed_after_captured_is_rejected_over_http(client) -> None:
    captured_body = _payload("payment.captured", "pay_1", "order_2", "captured")
    client.post(
        "/webhooks/razorpay",
        content=captured_body,
        headers={"X-Razorpay-Signature": _sign(captured_body), "X-Razorpay-Event-Id": "evt_1"},
    )

    failed_body = _payload("payment.failed", "pay_2", "order_2", "failed")
    response = client.post(
        "/webhooks/razorpay",
        content=failed_body,
        headers={"X-Razorpay-Signature": _sign(failed_body), "X-Razorpay-Event-Id": "evt_2"},
    )

    assert response.json()["outcome"] == "rejected_backward_transition"
