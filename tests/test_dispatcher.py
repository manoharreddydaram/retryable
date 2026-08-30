"""Dispatcher tests against a real Postgres instance (see conftest.py) and a
fake Razorpay client -- the HTTP client's own behaviour belongs to
test_razorpay_client.py; these tests cover outbox claiming, backoff
scheduling, and circuit-breaker coordination across multiple entries.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.execute.dispatcher import run_once
from src.execute.models import CircuitBreakerState, OutboxEntry
from src.execute.razorpay_client import PaymentLinkResult, RazorpayAPIError
from tests.conftest import make_settings


class _FakeClient:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    def create_payment_link(
        self, *, reference_id: str, amount_paise: int, order_id: str
    ) -> PaymentLinkResult:
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _pending_entry(order_id: str = "order_1", amount_paise: int = 50_000) -> OutboxEntry:
    now = datetime.now(UTC)
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
        [
            PaymentLinkResult(
                id="plink_1",
                short_url="https://rzp.io/l/x",
                status="created",
                recovered_from_conflict=False,
            )
        ]
    )
    summary = run_once(db_session, client, make_settings())

    db_session.refresh(entry)
    assert summary.completed == 1
    assert entry.status == "complete"
    assert entry.razorpay_payment_link_id == "plink_1"


def test_failed_dispatch_schedules_a_backoff_retry(db_session) -> None:
    entry = _pending_entry()
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient([RazorpayAPIError(500, "internal error")])
    summary = run_once(db_session, client, make_settings())

    db_session.refresh(entry)
    assert summary.failed == 1
    assert entry.status == "pending"
    assert entry.attempts == 1
    assert entry.next_attempt_at > datetime.now(UTC)


def test_entry_not_yet_due_is_not_claimed(db_session) -> None:
    entry = _pending_entry()
    entry.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    db_session.add(entry)
    db_session.flush()

    summary = run_once(db_session, _FakeClient([]), make_settings())

    assert summary.claimed == 0


def test_circuit_breaker_opens_and_skips_remaining_entries(db_session) -> None:
    for i in range(3):
        db_session.add(_pending_entry(order_id=f"order_{i}"))
    db_session.flush()

    client = _FakeClient([RazorpayAPIError(500, "down")] * 3)
    settings = make_settings(circuit_breaker_failure_threshold=2)
    summary = run_once(db_session, client, settings)

    # entries 1 and 2 fail and open the breaker (threshold=2); entry 3 is skipped
    assert summary.failed == 2
    assert summary.skipped_breaker_open == 1
    assert client.calls == 2

    breaker = db_session.get(CircuitBreakerState, "razorpay")
    assert breaker.state == "open"


def test_recovered_from_conflict_still_marks_complete(db_session) -> None:
    entry = _pending_entry()
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient(
        [
            PaymentLinkResult(
                id="plink_existing",
                short_url="https://rzp.io/l/y",
                status="created",
                recovered_from_conflict=True,
            )
        ]
    )
    summary = run_once(db_session, client, make_settings())

    db_session.refresh(entry)
    assert summary.recovered == 1
    assert summary.completed == 0
    assert entry.status == "complete"


def test_permanent_failure_after_max_attempts(db_session) -> None:
    entry = _pending_entry()
    entry.attempts = 9  # one more failure reaches the dispatcher's _MAX_ATTEMPTS = 10
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient([RazorpayAPIError(500, "still down")])
    summary = run_once(db_session, client, make_settings())

    db_session.refresh(entry)
    assert summary.failed_permanently == 1
    assert entry.status == "failed_permanently"


def test_a_second_call_is_never_made_for_an_already_complete_entry(db_session) -> None:
    entry = _pending_entry()
    db_session.add(entry)
    db_session.flush()

    client = _FakeClient(
        [
            PaymentLinkResult(
                id="plink_1",
                short_url="https://rzp.io/l/x",
                status="created",
                recovered_from_conflict=False,
            )
        ]
    )
    run_once(db_session, client, make_settings())
    run_once(db_session, client, make_settings())  # nothing pending left

    rows = db_session.execute(select(OutboxEntry)).scalars().all()
    assert len(rows) == 1
    assert client.calls == 1
