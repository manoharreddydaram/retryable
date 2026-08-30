"""Razorpay webhook signature verification.

HMAC-SHA256 of the raw request body, keyed with the webhook secret, compared
in constant time. The body must be the exact bytes Razorpay sent -- parsing
it to JSON and re-serialising before verifying would change the byte layout
(key order, whitespace) and break every signature.
"""

import hashlib
import hmac


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
