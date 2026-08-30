# Retryable

**Not every failed payment is retryable.**

Retryable diagnoses *why* each payment failed, recovers only the ones that can
be recovered, deliberately refuses the rest, and proves the difference in rupees
against a randomised control group.

Razorpay AI Buildathon 2026 — **Track 3: AI Revenue Recovery**

---

## The problem

When a payment fails, merchants do one of two things: nothing, or they retry
everything. Both leak money.

Abandoning recoverable revenue costs money. But chasing **unrecoverable**
failures also costs money — in messaging spend, in customer trust, and in
support load:

- Retrying an `insufficient_funds` failure thirty seconds later is guaranteed
  waste. Retrying it after payday is a different business entirely.
- Retrying a blocked card will never succeed. Not now, not in an hour, not ever.
- When an issuing bank's 3DS service goes down, messaging four hundred customers
  makes the merchant look broken for a failure that was never theirs.
- A gateway timeout may already have succeeded. Retrying it risks a double
  charge, which costs more than the original failure.

The expensive human judgment here is not writing a better follow-up message.
It is deciding **which failures are recoverable, by what mechanism, at what
moment, at what cost — and when to stop.**

## The thesis

> The model proposes. The policy engine disposes.
> **Only the policy engine can spend money.**

An LLM interprets the long tail of bank error semantics and builds a causal
hypothesis. A deterministic, versioned policy engine decides what — if anything
— happens next. Every executed action carries the ID of the rule that
authorised it, in an append-only audit log.

## What makes this different

Most recovery tooling optimises how hard you chase. This optimises **the
decision to stay silent.** The headline metric is not gross recovery. It is
incremental recovery over a control group, net of cost, alongside the
**wasted-attempt rate** — the money we did not spend chasing failures that were
never going to convert.

---

## Where AI is used, and where it deliberately isn't

The core thesis — the model proposes, the policy engine disposes — only means
something if it's specific. This is the actual boundary.

**Not used for:**

| Task | Used instead | Why |
|:--|:--|:--|
| Detecting revenue degradation | An EWMA / beta-binomial significance test | It's a statistics problem. An LLM here would be slower, non-reproducible, and no more accurate. |
| Classifying known Razorpay error codes | A deterministic lookup table | Covers ~70% of traffic. Free, instant, 100% accurate, auditable. |
| Selecting an intervention | A deterministic policy engine over versioned YAML | Money decisions must be reproducible and diffable — a rule you can `git blame`, not a probability you can't. |
| Any arithmetic on an amount | Plain Python, integer paise | Never let a model do money math. |
| Retry timing windows | A static lookup table by cohort | It's a lookup, not a reasoning problem. |
| Inserting amounts or links into a customer message | Deterministic slot-filling after generation | The model drafts prose only; it never touches the numbers. |

**Used for exactly three things:**

1. **Long-tail failure classification** — mapping novel, free-text bank/PSP
   error strings the rules table has never seen into our canonical taxonomy.
   Acquirers change their error vocabulary without notice; this tail is
   genuinely linguistic.
2. **Root-cause hypothesis** — synthesising a causal narrative from a
   multi-signal evidence bundle (error mix, card BIN, payment method, timing,
   merchant config). Every hypothesis must cite the specific evidence rows it
   used.
3. **Customer message drafting** — prose only, poured into fixed templates.

All three run through schema-constrained output (Pydantic, enum-only
taxonomy), temperature 0, with the prompt version hashed and recorded against
every diagnosis. If the model fails or returns something invalid, the system
falls back to the deterministic classifier — never to nothing.

---

## Designed failure scenarios

These are deliberate demo material, not accidents. Each is a real failure
mode this kind of system meets in production, designed for and given
explicit handling *before* being built — stated here now so it can't be
rewritten after the fact to match whatever actually happened.

| Stage | Scenario | What could go wrong | How it's handled |
|:--|:--|:--|:--|
| 2 | Duplicate / out-of-order webhook | A late `payment.captured` arrives for a payment already queued for chasing — the customer already paid | Event-ID dedupe plus a forward-only state machine cancels the queued outreach before it fires |
| 5 | A Razorpay API call times out after a possible side effect | The write may or may not have gone through | Retried with the *same* idempotency key, exponential backoff with jitter; a circuit breaker pauses the dispatcher rather than risk a double charge |
| 7 | The model proposes an out-of-catalog or policy-violating action | e.g. a discount, or an instant retry during a known bank outage | Schema validation and the policy engine reject it with a rule ID; both the proposal and the veto are logged |
| 8 | A false degradation alarm fires on a small sample | Normal noise in a tiny batch looks like a spike | A minimum-sample gate (n≥20) and a significance threshold suppress it |

Touch caps, spend caps, and a global kill switch bound every scenario above
from getting worse while it's being handled.

---

## Failure taxonomy

Every `payment.failed` webhook is classified the moment it arrives, using a
deterministic lookup table over Razorpay's own documented `error_reason`
values — 109 of them, covering the real vocabulary their gateway, banks, and
UPI apps actually produce. No AI involved, per the AI-usage boundary above:
this is a lookup, not a judgment call. The full mapping, sourced directly
from Razorpay's docs, is in
[src/classify/error_taxonomy.yaml](src/classify/error_taxonomy.yaml).

| Category | Recoverable? | Retry timing | Example `error_reason` |
|:--|:--:|:--|:--|
| `insufficient_funds` | Yes | Delayed | `insufficient_funds` |
| `auth_abandoned` | Yes | Immediate | `payment_cancelled`, `otp_expired` |
| `input_error_retriable` | Yes | Immediate | `incorrect_cvv`, `invalid_vpa` |
| `instrument_blocked` | No | Never — switch method | `card_expired`, `debit_instrument_blocked` |
| `issuer_declined` | No | Never — switch method | `card_declined`, `credit_limit_exceeded` |
| `infra_outage` | Yes | Wait for outage to clear | `bank_not_available`, `gateway_technical_error` |
| `ambiguous_verify_before_acting` | Maybe | Verify before any action | `payment_timed_out`, `order_already_paid` |
| `merchant_config_error` | No | Never — not the customer's fault | `invalid_order_id`, `invalid_amount` |
| `unknown` | — | Falls to Stage 7's LLM, or a human | anything not in the table |

Two categories are worth reading twice. `ambiguous_verify_before_acting` is
the double-charge trap: a gateway timeout can mean the payment actually went
through, so the only safe first move is to check the real status via the
Razorpay API, never to retry blind. `infra_outage` is the "don't blame the
customer" case from the problem statement above — a bank-side outage gets a
delay, not an apology email to four hundred people for a failure that was
never theirs.

---

## Policy engine

The only code in this project allowed to authorise spending money. Every
decision separates *what was proposed* (today, Stage 4's own category
rules; from Stage 7 on, an LLM) from *what was authorized* — the two can
differ, and when they do, both the proposal and the veto are recorded, not
just the final outcome.

A proposal passes through nine ordered gates — kill switch first, then the
confidence floor, category recoverability, touch cap, spend threshold,
batch ceiling, catalog membership, whether this category permits customer
contact at all, and finally quiet hours. The first gate that fires wins;
its `rule_id` is what ends up on the decision. The full catalog and rule
set are versioned data, not buried constants:
[policies/interventions.yaml](policies/interventions.yaml),
[policies/rules.yaml](policies/rules.yaml),
[policies/stopping_rules.yaml](policies/stopping_rules.yaml).

Two tests in [tests/test_policy_engine.py](tests/test_policy_engine.py)
demonstrate the designed failures directly: a proposal naming something
outside the five-intervention catalog (`give_10_percent_discount`) is
rejected with `OUT_OF_CATALOG`, and a proposal to contact a customer during
a documented bank outage is overridden to `wait` with
`CATEGORY_NOT_CUSTOMER_ACTIONABLE` — both before Stage 7's LLM exists to
actually produce a proposal like that.

---

## Status

🚧 In active development.

| Stage | Deliverable | Status |
|:--|:--|:--|
| 0 | Foundation: scaffold, Postgres, task runner, docs | ✅ |
| 1 | Schema + append-only hash-chained audit ledger | ✅ |
| 2 | Webhook ingress: HMAC verify, dedupe, state machine | ✅ |
| 3 | Canonical failure taxonomy + deterministic classifier | ✅ |
| 4 | Policy engine, intervention catalog, stopping rules | ✅ |
| 5 | Razorpay execution: outbox, idempotency, breaker | ⬜ |
| 6 | Evaluation harness with randomised control arm | ⬜ |
| 7 | LLM layer: long-tail classifier + diagnosis | ⬜ |
| 8 | Statistical degradation detector | ⬜ |
| 9 | UI: triage, decision detail, audit ledger, results | ⬜ |
| 10 | Documentation, evidence, demo | ⬜ |

The LLM arrives at stage 7 of 10, deliberately. See
[ADR-001](DECISIONS.md#adr-001--build-the-guardrails-before-the-model).

---

## Running it

Requires Docker Desktop and Python 3.13.

```bash
git clone https://github.com/<username>/retryable.git
cd retryable

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env

make db-up                         # Windows: .\tasks.ps1 db-up
make migrate                       # Windows: .\tasks.ps1 migrate
```

`make` is the canonical interface. Windows users can substitute
`.\tasks.ps1 <task>` for `make <task>` throughout.

---

## Repository map

| Path | Contents |
|:--|:--|
| `policies/` | Decision rules and the intervention catalog, as versioned YAML |
| `eval/` | Batch generator, payer simulator, evaluation runner |
| `eval/results/` | Committed evaluation output — the evidence behind every number |
| `prompts/` | Versioned LLM prompts, hashed and recorded on each diagnosis |
| `src/detect/` | Statistical degradation detection. No LLM, by design. |
| `src/policy/` | The decision engine. The only code that may authorise spend. |
| `src/ledger/` | Append-only, hash-chained audit log |
| `DECISIONS.md` | Architecture decision records |
| `FAILURES.md` | What broke during the build, and how it was fixed |
| `EVALUATION.md` | Methodology, and an honest account of what is simulated |

`policies/` and `eval/` sit at the top level alongside `src/` on purpose. The
decision rules and the evidence are first-class artifacts of this project, not
implementation details.

---

## Documentation

- [DECISIONS.md](DECISIONS.md) — why the architecture looks like this
- [FAILURES.md](FAILURES.md) — what broke, and how we got out
- [EVALUATION.md](EVALUATION.md) — how the numbers were produced
