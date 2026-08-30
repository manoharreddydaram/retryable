"""Pure unit tests for the forward-only transition rule. No database."""

from src.ingest.state_machine import PaymentStatus, decide_transition


def test_new_subject_is_always_allowed() -> None:
    decision = decide_transition(None, PaymentStatus.FAILED)
    assert decision.allowed is True
    assert decision.changed is True


def test_failed_to_captured_is_allowed_and_changed() -> None:
    decision = decide_transition(PaymentStatus.FAILED, PaymentStatus.CAPTURED)
    assert decision.allowed is True
    assert decision.changed is True


def test_failed_to_failed_is_allowed_but_unchanged() -> None:
    decision = decide_transition(PaymentStatus.FAILED, PaymentStatus.FAILED)
    assert decision.allowed is True
    assert decision.changed is False


def test_captured_to_captured_is_allowed_but_unchanged() -> None:
    decision = decide_transition(PaymentStatus.CAPTURED, PaymentStatus.CAPTURED)
    assert decision.allowed is True
    assert decision.changed is False


def test_captured_to_failed_is_rejected() -> None:
    decision = decide_transition(PaymentStatus.CAPTURED, PaymentStatus.FAILED)
    assert decision.allowed is False
    assert "captured" in decision.reason.lower()
