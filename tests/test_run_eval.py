"""End-to-end eval harness test against a real Postgres instance (see
conftest.py) and a fake, always-succeeding Razorpay client -- the client's
own behaviour belongs to test_razorpay_client.py. This proves the eval
harness's own wiring: both arms produce real decisions, treatment
suppresses what control blindly sends to, and the metrics reflect it.

The circuit breaker is reset before this test for the same reason
test_dispatcher.py resets it: this database also serves real eval/dispatch
runs, which can leave it open, and this test needs a known starting point
rather than depending on however much real time has passed since then.
"""

import uuid

import pytest
from sqlalchemy import delete

from eval.batch_generator import generate_batch, split_arms
from eval.control_arm import CONTROL_ARM_RULE_ID
from eval.run_eval import run_evaluation
from src.execute.models import CircuitBreakerState
from src.execute.razorpay_client import PaymentLinkResult
from tests.conftest import make_settings


@pytest.fixture(autouse=True)
def _reset_circuit_breaker(db_session):
    db_session.execute(delete(CircuitBreakerState))
    db_session.flush()


class _AlwaysSucceedsClient:
    def create_payment_link(
        self, *, reference_id: str, amount_paise: int, order_id: str
    ) -> PaymentLinkResult:
        return PaymentLinkResult(
            id=f"plink_{uuid.uuid4().hex[:8]}",
            short_url=f"https://rzp.io/l/{uuid.uuid4().hex[:8]}",
            status="created",
            recovered_from_conflict=False,
        )


def test_eval_run_produces_metrics_and_control_wastes_more_than_treatment(db_session) -> None:
    settings = make_settings()
    client = _AlwaysSucceedsClient()

    metrics = run_evaluation(db_session, client, settings, seed=123, batch_size=120)

    expected_batch = generate_batch(120, seed=123)
    expected_treatment, expected_control = split_arms(expected_batch, seed=123)

    assert metrics.batch_size == 120
    # Control sends unconditionally -- every control-arm failure gets a real send.
    assert metrics.control.attempted_sends == len(expected_control)
    # Treatment only sends for recoverable, customer-actionable categories -- some, not all.
    assert 0 < metrics.treatment.attempted_sends < len(expected_treatment)

    # The point of the whole project: control sends to everyone, including
    # categories that structurally can't convert. Treatment suppresses
    # those entirely, so its wasted-attempt rate must be materially lower.
    assert metrics.treatment.wasted_attempt_rate < metrics.control.wasted_attempt_rate

    assert CONTROL_ARM_RULE_ID not in metrics.blocked_actions
    assert metrics.stopping_rule_violations == 0
    assert metrics.double_charge_incidents == 0
    assert (
        metrics.known_reason_accuracy == 1.0
    )  # a lookup can't misclassify a string that's in its own table
