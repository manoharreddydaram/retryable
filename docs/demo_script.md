# Demo script

A walkthrough for the submission recording. Written by Claude Code as prep
material, not a substitute for FAILURES.md or the recording itself — both
of those need the human's real experience, not a script.

Two things before recording:

1. Both servers running: `make run` (:8000) and `make web` (:5173).
2. A non-empty `RAZORPAY_WEBHOOK_SECRET` in `.env` — the signature check
   fails closed on an empty secret (`src/ingest/signature.py`), so the live
   webhook steps below won't authenticate against a blank one. Any string
   works for a local demo; it only needs to match what you sign with below.

---

## 1. The pitch (30 seconds)

> "Not every failed payment is retryable. Retrying `insufficient_funds`
> thirty seconds later is guaranteed waste. Retrying a blocked card is waste
> forever. Retryable's whole job is telling the difference — and proving it
> in rupees against a control group, not just asserting it."

Open **Live Triage**. Point at the **Source** column: some decisions say
`rules`, and once a real `ANTHROPIC_API_KEY` is in `.env` and
`make diagnose` has run at least once, some will say `LLM` — the same
policy engine authorizes both, visible in the **Decision** column either way.

---

## 2. Designed failure #1 — duplicate / out-of-order webhook (Stage 2)

Live and fully reproducible. Send a failure, then a late capture for the
same order, and watch the second one recover it instead of double-chasing
a customer who already paid.

Compute a valid signature and send both webhooks (adjust `SECRET` to match
your `.env`):

```bash
python -c "
import hashlib, hmac, json, urllib.request

SECRET = 'whsec_demo_secret'  # must match RAZORPAY_WEBHOOK_SECRET in .env

def send(event, payment_id, order_id, status):
    body = json.dumps({
        'entity': 'event', 'event': event, 'contains': ['payment'],
        'payload': {'payment': {'entity': {
            'id': payment_id, 'amount': 50000, 'currency': 'INR',
            'status': status, 'order_id': order_id, 'method': 'card',
        }}},
        'created_at': 1700000000,
    }).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        'http://localhost:8000/webhooks/razorpay', data=body, method='POST',
        headers={'X-Razorpay-Signature': sig, 'X-Razorpay-Event-Id': event + '_' + payment_id},
    )
    print(urllib.request.urlopen(req).read().decode())

send('payment.failed', 'pay_demo_1', 'order_demo_1', 'failed')
send('payment.captured', 'pay_demo_2', 'order_demo_1', 'captured')
"
```

The first response's `outcome` is `applied`; the second is `recovered`.
Refresh **Live Triage** — `order_demo_1` shows `captured`. Open **Audit
Ledger** and find both `webhook.applied` entries for `order_demo_1` — the
forward-only state machine and event-ID dedupe are why a third, out-of-order
`payment.failed` for the same order would be rejected rather than reopening
a settled payment (`tests/test_webhook_endpoint.py` proves the rejected
case directly, if you'd rather show that in code than trigger it live).

---

## 3. Designed failure #2 — the LLM proposes something the policy engine rejects (Stage 7)

Needs a real `ANTHROPIC_API_KEY` in `.env` to show live. With one:

```bash
make diagnose
```

Then find an `unknown`-category order in Live Triage tagged **LLM** and
open its Decision Detail. If the diagnosis suggested something the category
doesn't actually permit (e.g. contacting a customer during an
`infra_outage`), the **Rule trace** section shows `CATEGORY_NOT_CUSTOMER_ACTIONABLE`
with `Overridden: Yes` — the proposal and the veto both visible, not just
the final outcome.

Without a key: this exact scenario is `test_policy_engine_still_overrides_a_contextually_wrong_llm_suggestion`
in `tests/test_diagnose_service.py` — a mocked model response proposing
`send_payment_link` for an `infra_outage` diagnosis, overridden the same
way. Worth showing in an editor rather than skipping the failure entirely.

---

## 4. Designed failure #3 — a Razorpay call times out after a possible side effect (Stage 5)

This one already happened for real and is still sitting in the database —
no need to force it live.

```bash
python -c "
from src.db.base import SessionLocal
from sqlalchemy import text
with SessionLocal() as s:
    print(dict(s.execute(text('SELECT * FROM circuit_breaker_state')).mappings().first()))
"
```

This prints a real circuit breaker row: `state: open`, opened after five
consecutive `429: Too many requests` responses from Razorpay's test-mode
API during a real `make eval` run (see the README's Evaluation harness
section, and `FAILURES.md` once it's written). Every affected order's
outbox entry is `pending`, not lost — visible on Live Triage's Outbox
column — waiting for `make dispatch` to resume them once the limit window
passes. Explain the mechanism this protects: retrying with the *same*
`reference_id` means a resumed dispatch either creates the link for the
first time or discovers it already exists, never both.

---

## 5. Designed failure #4 — a false degradation alarm on a small sample (Stage 8)

Live and currently reproducible exactly as-is, because the dev database's
recent traffic genuinely is this small:

```bash
make detect
```

Output shows every cohort suppressed with `insufficient_sample` — real,
not staged, because there simply haven't been 20 payments of any kind in
the last hour. That's the n≥20 floor from CLAUDE.md doing its job, not an
absence of activity. To show *why* the floor is load-bearing rather than
decorative, open `tests/test_detect_significance.py` and point at
`test_tiny_sample_alone_is_not_a_safe_gate`: 2 failures out of 3 attempts,
on its own, computes over 95% confidence of degradation against an
established baseline — the significance test alone would have fired.

---

## 6. Close

Open **Results**. State the incremental lift and the wasted-attempt rate
side by side — recovery and restraint are the same number, reported
honestly with a control group, not asserted.
