"""Thin wrapper around the two Razorpay REST calls this project executes:
creating a payment link, and checking a payment's real status.

Razorpay's Payment Links API has no native idempotency-key header -- that
exists only for Payouts, Direct Transfers and Refunds, verified against
their docs. Instead, `reference_id` is enforced unique per merchant, and
creating a link whose reference_id was already used returns an explicit
"already exists" error. That error is this project's actual idempotency
mechanism: after a timeout, retrying with the *same* reference_id either
creates the link for the first time, or hits "already exists" -- proving the
first attempt already succeeded -- in which case the existing link is
fetched and treated as success, not failure. Either way, exactly one link
is ever created per decision.

notify.sms and notify.email are hard-set to false on every call. This
project does not send real messages through any channel, including
Razorpay's own -- see CLAUDE.md's build constraints. The "channel" a
customer would notionally be reached on is a label the Stage 6 payer
simulator reasons about, never a real send.
"""

import time
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class RazorpayClientError(Exception):
    """Base for every error this client raises."""


class RazorpayAPIError(RazorpayClientError):
    """Razorpay responded with an error status that isn't a recoverable conflict."""

    def __init__(self, status_code: int, description: str) -> None:
        self.status_code = status_code
        self.description = description
        super().__init__(f"{status_code}: {description}")


class RazorpayTimeoutError(RazorpayClientError):
    """The call may or may not have reached Razorpay -- outcome unknown."""


@dataclass(frozen=True)
class PaymentLinkResult:
    id: str
    short_url: str
    status: str
    recovered_from_conflict: bool


class RazorpayClient:
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        base_url: str = "https://api.razorpay.com/v1",
        http_client: httpx.Client | None = None,
        min_interval_seconds: float = 1.0,
    ) -> None:
        """min_interval_seconds paces real calls client-side. Razorpay does
        not publish an exact test-mode rate limit, and it's tighter than it
        might seem: two separate real eval runs each hit a 429 after about
        5 consecutive create-payment-link calls, even with 0.5s spacing
        between them. This can't be dodged with certainty without a
        published number to target -- what matters is that hitting it is
        handled safely: the circuit breaker opens, remaining entries stay
        untouched and pending, and a later `make dispatch` resumes them
        once the limit window has passed. Pass 0.0 in tests -- a mocked
        transport has nothing to rate-limit and no reason to sleep."""
        self._auth = (key_id, key_secret)
        self._client = http_client or httpx.Client(base_url=base_url, timeout=10.0)
        self._min_interval_seconds = min_interval_seconds
        self._last_call_at: float | None = None

    def _throttle(self) -> None:
        if self._min_interval_seconds <= 0 or self._last_call_at is None:
            self._last_call_at = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_call_at
        remaining = self._min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_call_at = time.monotonic()

    def create_payment_link(
        self, *, reference_id: str, amount_paise: int, order_id: str, currency: str = "INR"
    ) -> PaymentLinkResult:
        payload = {
            "amount": amount_paise,
            "currency": currency,
            "reference_id": reference_id,
            "description": f"Payment for order {order_id}",
            "accept_partial": False,
            "reminder_enable": False,
            "notify": {"sms": False, "email": False},
        }

        try:
            response = self._post("/payment_links", payload)
        except RazorpayAPIError as exc:
            if _is_duplicate_reference_error(exc):
                existing = self.fetch_by_reference_id(reference_id)
                if existing is not None:
                    return existing
            raise

        return PaymentLinkResult(
            id=response["id"],
            short_url=response["short_url"],
            status=response["status"],
            recovered_from_conflict=False,
        )

    def fetch_by_reference_id(self, reference_id: str) -> PaymentLinkResult | None:
        response = self._get("/payment_links", params={"reference_id": reference_id, "count": 1})
        items = response.get("items", [])
        if not items:
            return None
        item = items[0]
        return PaymentLinkResult(
            id=item["id"],
            short_url=item["short_url"],
            status=item["status"],
            recovered_from_conflict=True,
        )

    def get_payment_status(self, payment_id: str) -> str:
        response = self._get(f"/payments/{payment_id}")
        return response["status"]

    @retry(
        retry=retry_if_exception_type(httpx.ConnectError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, max=2),
        reraise=True,
    )
    def _post(self, path: str, payload: dict) -> dict:
        self._throttle()
        try:
            response = self._client.post(path, json=payload, auth=self._auth)
        except httpx.TimeoutException as exc:
            raise RazorpayTimeoutError(f"POST {path} timed out: {exc}") from exc
        return _raise_for_status(response)

    @retry(
        retry=retry_if_exception_type(httpx.ConnectError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, max=2),
        reraise=True,
    )
    def _get(self, path: str, params: dict | None = None) -> dict:
        self._throttle()
        try:
            response = self._client.get(path, params=params, auth=self._auth)
        except httpx.TimeoutException as exc:
            raise RazorpayTimeoutError(f"GET {path} timed out: {exc}") from exc
        return _raise_for_status(response)


def _raise_for_status(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        content_type = response.headers.get("content-type", "")
        body = response.json() if content_type.startswith("application/json") else {}
        description = body.get("error", {}).get("description", response.text)
        raise RazorpayAPIError(response.status_code, description)
    return response.json()


def _is_duplicate_reference_error(exc: RazorpayAPIError) -> bool:
    return "already exists" in exc.description.lower()
