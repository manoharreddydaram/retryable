"""Manual, one-off verification that this project can actually reach
Razorpay's test-mode API with the credentials in your .env. Not part of the
automated test suite -- that suite is fully mocked (see
tests/test_razorpay_client.py) precisely so it never needs real credentials
or a network call. Run this yourself once you've added real rzp_test_
credentials, to prove connectivity *and* the idempotency recovery path
against the real API, not just against a mock.

Usage:
    python scripts/verify_razorpay_connection.py
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.execute.razorpay_client import RazorpayClient, RazorpayClientError  # noqa: E402


def main() -> int:
    settings = get_settings()

    if not settings.razorpay_key_id or settings.razorpay_key_id == "rzp_test_xxxxxxxxxxxx":
        print("RAZORPAY_KEY_ID is not set to a real value in .env -- nothing to verify.")
        return 1
    if not settings.razorpay_key_secret:
        print("RAZORPAY_KEY_SECRET is empty in .env -- nothing to verify.")
        return 1

    client = RazorpayClient(settings.razorpay_key_id, settings.razorpay_key_secret)
    reference_id = f"rtx-smoketest-{uuid.uuid4().hex[:12]}"

    print(f"Creating a test-mode payment link (reference_id={reference_id})...")
    try:
        result = client.create_payment_link(
            reference_id=reference_id, amount_paise=100, order_id="smoketest"
        )
    except RazorpayClientError as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"OK  -- id={result.id}")
    print(f"    short_url={result.short_url}")
    print(f"    status={result.status}")

    print("\nRetrying the exact same reference_id, to confirm the idempotency recovery path...")
    try:
        second = client.create_payment_link(
            reference_id=reference_id, amount_paise=100, order_id="smoketest"
        )
    except RazorpayClientError as exc:
        print(f"FAILED on the second call: {exc}")
        return 1

    if second.id != result.id or not second.recovered_from_conflict:
        print(
            "UNEXPECTED: the second call did not recover the same link. Check razorpay_client.py."
        )
        return 1

    print(f"OK  -- recovered the same link (id={second.id}) instead of creating a duplicate.")
    print("\nBoth checks passed: connectivity is real, and duplicate-reference recovery works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
