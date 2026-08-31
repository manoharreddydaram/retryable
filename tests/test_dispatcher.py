"""Dispatcher tests against a real Postgres instance (see conftest.py) and a
fake Razorpay client -- the HTTP client's own behaviour belongs to
test_razorpay_client.py; these tests cover outbox claiming, backoff
scheduling, and circuit-breaker coordination.

This database also serves real eval and dispatch runs (see run_eval.py /
run_dispatcher.py), which can leave real pending outbox rows and a real
circuit_breaker_state row behind -- for example, a batch that hit
Razorpay's test-mode rate limit mid-run leaves entries pending with a
future next_attempt_at, and an open breaker, exactly as designed. Every
test here is written to be correct regardless of that ambient state: the
fake client answers by reference_id (so a stray unrelated row just gets a
harmless default success instead of exhausting a strict response queue and
crashing), the breaker is reset to closed before each test, and assertions
check the specific rows each test created rather than trusting global
DispatchSummary counts that ambient rows would also contribute to.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from src.execute.dispatcher import run_once
from src.execute.models import CircuitBreakerState, OutboxEntry
from src.execute.razorpay_client import PaymentLinkResult, RazorpayAPIError
from tests.conftest import make_settings


class _FakeClient:
    """Answers a specific reference_id exactly as told. Anything else --
    ambient rows left over from real usage -- gets a harmless generic
    success, so they can never crash a test or masquerade as one of its
    own failures."""

    def __init__(self, responses_by_reference_id: dict | None = None) -> None:
        self._by_ref = dict(responses_by_reference_id or {})
        self.calls = 0
        self.called_with: list[str] = []

    def create_payment_link(
        self, *, reference_id: str, amount_paise: int, order_id: str
    ) -> PaymentLinkResult:
        self.calls += 1
        self.called_with.append(reference_id)
        response = self._by_ref.get(reference_id)
        if response is None:
            return PaymentLinkResult(
                id=f"plink_ambient_{self.calls}",
                short_url="https://rzp.io/l/ambient",
                status="created",
                recovered_from_conflict=False,
            )
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def _reset_circuit_breaker(db_session):
    """Single shared row (service='razorpay'); a real run can leave it open.
    Every test in this file needs a known 'closed' starting point."""
    db_session.execute(delete(CircuitBreakerState))
    db_session.flush()


def _pending_entry(amount_paise: int = 50_000) -> OutboxEntry:
    now = datetime.now(UTC)
    order_id = f"order_{uuid.uuid4().hex[:8]}"
    return OutboxEntry(
        decision_id=uuid.uuid4(),
        idempotency_key=f"rtx-{uuid.uuid4().hex}",
        intervention="send_payment_link",
        order_id=order_id,
        amount_paise=amount_paise,
        status="pending",
        attempts=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )


def test_successful_dispatch_marks_the_entry_complete(db_session) -> None:
    entry = _pending_entry()
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient(
        {
            entry.idempotency_key: PaymentLinkResult(
                id="plink_1",
                short_url="https://rzp.io/l/x",
                status="created",
                recovered_from_conflict=False,
            )
        }
    )
    run_once(db_session, client, make_settings(), limit=500)

    db_session.refresh(entry)
    assert entry.status == "complete"
    assert entry.razorpay_payment_link_id == "plink_1"


def test_failed_dispatch_schedules_a_backoff_retry(db_session) -> None:
    entry = _pending_entry()
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient({entry.idempotency_key: RazorpayAPIError(500, "internal error")})
    run_once(db_session, client, make_settings(), limit=500)

    db_session.refresh(entry)
    assert entry.status == "pending"
    assert entry.attempts == 1
    assert entry.next_attempt_at > datetime.now(UTC)


def test_entry_not_yet_due_is_not_claimed(db_session) -> None:
    entry = _pending_entry()
    entry.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient()
    run_once(db_session, client, make_settings(), limit=500)

    db_session.refresh(entry)
    assert entry.status == "pending"
    assert entry.attempts == 0
    assert entry.idempotency_key not in client.called_with


def test_circuit_breaker_opens_and_skips_remaining_entries(db_session) -> None:
    entries = [_pending_entry() for _ in range(3)]
    for entry in entries:
        db_session.add(entry)
    db_session.flush()

    client = _FakeClient({e.idempotency_key: RazorpayAPIError(500, "down") for e in entries})
    settings = make_settings(circuit_breaker_failure_threshold=2)
    run_once(db_session, client, settings, limit=500)

    for entry in entries:
        db_session.refresh(entry)
    attempted = [e for e in entries if e.attempts > 0]
    skipped = [e for e in entries if e.attempts == 0]

    # threshold=2: whichever two of these three are processed first both
    # fail and open the breaker; the third is left pending, untouched.
    assert len(attempted) == 2
    assert len(skipped) == 1

    breaker = db_session.get(CircuitBreakerState, "razorpay")
    assert breaker.state == "open"


def test_recovered_from_conflict_still_marks_complete(db_session) -> None:
    entry = _pending_entry()
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient(
        {
            entry.idempotency_key: PaymentLinkResult(
                id="plink_existing",
                short_url="https://rzp.io/l/y",
                status="created",
                recovered_from_conflict=True,
            )
        }
    )
    run_once(db_session, client, make_settings(), limit=500)

    db_session.refresh(entry)
    assert entry.status == "complete"
    assert entry.razorpay_payment_link_id == "plink_existing"


def test_permanent_failure_after_max_attempts(db_session) -> None:
    entry = _pending_entry()
    entry.attempts = 9  # one more failure reaches the dispatcher's _MAX_ATTEMPTS = 10
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient({entry.idempotency_key: RazorpayAPIError(500, "still down")})
    run_once(db_session, client, make_settings(), limit=500)

    db_session.refresh(entry)
    assert entry.status == "failed_permanently"


def test_a_second_call_is_never_made_for_an_already_complete_entry(db_session) -> None:
    entry = _pending_entry()
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient(
        {
            entry.idempotency_key: PaymentLinkResult(
                id="plink_1",
                short_url="https://rzp.io/l/x",
                status="created",
                recovered_from_conflict=False,
            )
        }
    )
    run_once(db_session, client, make_settings(), limit=500)
    run_once(db_session, client, make_settings(), limit=500)  # this entry is no longer pending

    db_session.refresh(entry)
    assert entry.status == "complete"
    assert client.called_with.count(entry.idempotency_key) == 1
