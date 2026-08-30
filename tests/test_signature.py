"""Pure unit tests for HMAC signature verification. No database involved."""

import hashlib
import hmac

from src.ingest.signature import verify_signature

SECRET = "whsec_test_12345"
BODY = b'{"event":"payment.failed","payload":{}}'


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_valid_signature_is_accepted() -> None:
    assert verify_signature(BODY, _sign(BODY, SECRET), SECRET) is True


def test_tampered_body_is_rejected() -> None:
    tampered = BODY.replace(b"failed", b"captured")
    assert verify_signature(tampered, _sign(BODY, SECRET), SECRET) is False


def test_wrong_secret_is_rejected() -> None:
    assert verify_signature(BODY, _sign(BODY, "wrong_secret"), SECRET) is False


def test_missing_signature_is_rejected() -> None:
    assert verify_signature(BODY, "", SECRET) is False


def test_missing_secret_is_rejected() -> None:
    assert verify_signature(BODY, _sign(BODY, SECRET), "") is False
