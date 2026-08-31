"""Tests for the Anthropic client wrapper, against a mocked HTTP transport
(httpx2.MockTransport) -- no real network call, no real credentials needed.
max_retries=0 on the test client avoids the SDK's own retry backoff turning
these into slow tests; that retry behavior belongs to Anthropic's SDK, not
to code this project owns.
"""

import json

import anthropic
import httpx2
import pytest

from src.diagnose.client import DiagnosisFailed, call_llm
from src.diagnose.evidence import EvidenceBundle, EvidenceItem
from tests.conftest import make_settings

_BUNDLE = EvidenceBundle(items=[EvidenceItem("E1", "test evidence")])


def _client_with(handler) -> anthropic.Anthropic:
    transport = httpx2.MockTransport(handler)
    http_client = httpx2.Client(transport=transport)
    return anthropic.Anthropic(api_key="fake-key-for-tests", http_client=http_client, max_retries=0)


def _text_response(payload: dict) -> httpx2.Response:
    body = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return httpx2.Response(200, json=body)


def _error_response(status: int) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"type": "x", "message": "simulated"}})


def test_missing_api_key_fails_without_touching_the_network() -> None:
    settings = make_settings(anthropic_api_key="")
    with pytest.raises(DiagnosisFailed) as exc_info:
        call_llm(_BUNDLE, settings)
    assert exc_info.value.reason == "no_api_key"


def test_successful_call_returns_a_valid_diagnosis() -> None:
    def handler(request):
        return _text_response(
            {
                "category": "unknown",
                "confidence": 0.4,
                "reasoning": "not enough signal to decide responsibly",
                "cited_evidence_ids": ["E1"],
                "suggested_intervention": "escalate_to_human",
            }
        )

    settings = make_settings(anthropic_api_key="fake")
    output, used_hash, raw = call_llm(_BUNDLE, settings, client=_client_with(handler))

    assert output.category.value == "unknown"
    assert output.confidence == 0.4
    assert output.cited_evidence_ids == ["E1"]
    assert len(used_hash) == 64
    assert raw


def test_hallucinated_citation_is_rejected() -> None:
    def handler(request):
        return _text_response(
            {
                "category": "insufficient_funds",
                "confidence": 0.9,
                "reasoning": "citing evidence that was never provided",
                "cited_evidence_ids": ["E1", "E99"],  # E99 never appeared in the bundle
                "suggested_intervention": "send_payment_link",
            }
        )

    settings = make_settings(anthropic_api_key="fake")
    with pytest.raises(DiagnosisFailed) as exc_info:
        call_llm(_BUNDLE, settings, client=_client_with(handler))
    assert exc_info.value.reason == "hallucinated_citation"


def test_authentication_error_degrades_gracefully() -> None:
    def handler(request):
        return _error_response(401)

    settings = make_settings(anthropic_api_key="fake")
    with pytest.raises(DiagnosisFailed) as exc_info:
        call_llm(_BUNDLE, settings, client=_client_with(handler))
    assert exc_info.value.reason == "authentication_error"


def test_rate_limit_error_degrades_gracefully() -> None:
    def handler(request):
        return _error_response(429)

    settings = make_settings(anthropic_api_key="fake")
    with pytest.raises(DiagnosisFailed) as exc_info:
        call_llm(_BUNDLE, settings, client=_client_with(handler))
    assert exc_info.value.reason == "rate_limited"


def test_server_error_degrades_gracefully() -> None:
    def handler(request):
        return _error_response(500)

    settings = make_settings(anthropic_api_key="fake")
    with pytest.raises(DiagnosisFailed) as exc_info:
        call_llm(_BUNDLE, settings, client=_client_with(handler))
    assert exc_info.value.reason == "api_error_500"


def test_connection_error_degrades_gracefully() -> None:
    def handler(request):
        raise httpx2.ConnectError("simulated network failure", request=request)

    settings = make_settings(anthropic_api_key="fake")
    with pytest.raises(DiagnosisFailed) as exc_info:
        call_llm(_BUNDLE, settings, client=_client_with(handler))
    assert exc_info.value.reason == "connection_error"
