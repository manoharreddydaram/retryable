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
taxonomy), with the prompt version hashed and recorded against every
diagnosis. If the model fails or returns something invalid, the system falls
back to the deterministic classifier — never to nothing. (Determinism here no
longer comes from `temperature 0` — see the LLM layer section below for why.)

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

## Execution and idempotency

Razorpay's Payment Links API has no native idempotency-key header — that
exists only for Payouts, Direct Transfers, and Refunds (verified against
their docs, not assumed). Instead, every payment link created here carries
a `reference_id` derived from the decision's own ID, and Razorpay enforces
`reference_id` uniqueness itself: a second create with the same value
returns an explicit "already exists" error instead of a second link.

That error *is* this project's idempotency mechanism. When a create call
times out — the exact case designed failure #3 covers — the outcome is
unknown: it may have reached Razorpay and succeeded, or it may not have.
Retrying with the same reference_id resolves this either way: a fresh
create succeeds normally, or an "already exists" error proves the first
attempt already worked, in which case the existing link is fetched and
treated as success, not failure. Either way, exactly one link is ever
created per decision — proven in
[tests/test_razorpay_client.py](tests/test_razorpay_client.py) against a
mocked transport, and verifiable against the real API with
`make verify-razorpay` once real test-mode credentials are in `.env`.

Every authorized decision that calls Razorpay is written to an outbox entry
in the *same transaction* as the decision it belongs to (ADR-003) — the
decision and the intent to act on it can never diverge. A separate
dispatcher (`make dispatch`) polls for entries whose retry time has come,
claiming rows with `SELECT ... FOR UPDATE SKIP LOCKED` so it's safe to run
concurrently. Failures back off exponentially with jitter and feed a
three-state circuit breaker shared across dispatcher runs: five consecutive
failures open it, and every other entry due in that run is left pending
rather than each taking its own doomed shot at a service that's already
down.

---

## Evaluation harness

`make eval` generates a seeded synthetic batch of failed payments, splits it
70/30 into treatment and control by a separate seeded shuffle, and runs
*both* arms through the same real pipeline: treatment through Stage 3's
classifier and Stage 4's policy engine, control through a fixed "retry once,
one hour later, regardless of cause" rule that deliberately bypasses the
policy engine entirely — the naive baseline this track's bar exists to beat.
Both arms are then dispatched by the *same* Stage 5 dispatcher against the
real Razorpay API, so any measured difference between them is attributable
to the decision, not to different execution reliability underneath it.

The batch's category mix is anchored, where a citation actually applies, to
a published dunning benchmark on card-decline composition; the payer
simulator's conversion propensities are sourced from published dunning and
cart-abandonment recovery benchmarks, cited inline in
[eval/propensities.yaml](eval/propensities.yaml), and blind to which arm
triggered a send or which rule authorized it — it sees only category and
timing. Every synthetic failure's timestamp is drawn from a fixed epoch, not
real wall-clock time, specifically so results (including which entries fall
inside quiet hours) are identical for a given `--seed` regardless of what
time of day `make eval` is actually run.

**A real finding, not a simulated one:** Razorpay does not publish an exact
test-mode rate limit, and it is tighter than expected — two independent
evaluation runs each hit an HTTP 429 after roughly five consecutive
payment-link creations, even with client-side pacing between calls. This
can't be reliably dodged without a published number to target, so it isn't
treated as an error: the circuit breaker opens exactly as designed, every
other entry due in that run is left safely pending, and a later
`make dispatch` resumes them once the limit window has passed. `make eval`
reports how many entries are still pending for exactly this reason, rather
than presenting a partially-drained batch as a complete one.

---

## LLM layer: long-tail diagnosis

Every `unknown`-category failure — whatever Stage 3's lookup table doesn't
recognise — is eligible for a second look from Claude, run as a separate,
on-demand pass (`make diagnose`) rather than inline during webhook ingest:
Razorpay expects a webhook response within 5 seconds, and an LLM round-trip
cannot reliably fit inside that budget.

The call sends Claude a small evidence bundle — the raw error text, method,
amount, time of day, and same-error / total-failure counts drawn from the
last 24 hours (never claimed as statistically significant; that judgment
stays in Stage 8's detector) — and asks for exactly one thing back: a
category from the same closed taxonomy Stage 3 uses, a confidence, a
reasoning string, the specific evidence IDs it relied on, and one suggested
intervention from the same five-item catalog Stage 4 uses. All of it is
schema-constrained (`output_format=DiagnosisOutput` in
[src/diagnose/schemas.py](src/diagnose/schemas.py)) — the model cannot name a
category or intervention that doesn't exist, only apply a real one
incorrectly. A cited evidence ID that wasn't actually in the bundle sent is
rejected outright before the result is ever used. Every call, successful or
not, is durably recorded in `diagnoses`
([src/diagnose/models.py](src/diagnose/models.py)) with its full evidence
bundle, prompt hash, and raw response — a failed call degrades this order
back to `escalate_to_human` via the existing confidence-floor gate, never to
silence.

**A real finding, not an assumption:** this project's design originally
called for `temperature 0`, written before this model generation existed.
Verified directly against the installed SDK (`anthropic==1.2.0`):
`messages.parse()` has no `temperature` parameter at all for Claude Opus 5 —
passing one is rejected outright, not merely ignored. The determinism this
project actually needs turns out to live elsewhere and never depended on it:
the closed-enum schema, the policy engine's deterministic gates regardless of
the model's exact wording, and an audit trail that records every call either
way. The model's prose was always the one part that couldn't be bit-for-bit
reproducible, and temperature 0 on the old API only ever reduced that
variance, never removed it.

A confident, citation-valid suggestion is run through the *exact same*
`decide()` used everywhere else in this project — including designed failure
#2. A diagnosis of `infra_outage` (correctly schema-valid) that nonetheless
suggests `send_payment_link` (a real intervention, wrong for this category)
is overridden to `wait` by the existing `CATEGORY_NOT_CUSTOMER_ACTIONABLE`
rule, with both the LLM's proposal and the engine's veto recorded — proven in
[tests/test_diagnose_service.py](tests/test_diagnose_service.py) against a
mocked model response, no real API key required.

---

## Statistical degradation detection

Every `make detect` pass compares two cohort shapes against their own
tracked history: the system-wide failure rate (failures against every
attempt in the last hour — the safety-net signal), and each taxonomy
category's *share* of failures (this category's count against all failures
in the window, since category is only ever set on a failed payment — there
is no "successful infra_outage" to measure a rate against). No LLM is
involved in either: per the AI-usage boundary above, distributional change
is a statistics problem, and this project's own requirements name the tool
explicitly — EWMA for the baseline, a beta-binomial significance test for
the decision.

Each cohort's baseline is an exponentially weighted moving average of its
own recent rate — adaptive, not a fixed historical constant — persisted in
`detector_baselines` ([src/detect/models.py](src/detect/models.py)). Every
new window is tested against that baseline by modelling both as Beta
distributions (the baseline as a scaled rate, the recent window as a flat
prior updated by its own counts) and computing the exact probability that
the recent rate is truly higher, via numerical integration
([src/detect/significance.py](src/detect/significance.py)) rather than
Monte Carlo — no seed, and the same four numbers always produce the same
probability.

**Designed failure #4, proven rather than assumed:** the significance test
alone is not a safe gate on a small sample.
[tests/test_detect_significance.py](tests/test_detect_significance.py)
demonstrates this directly — 2 failures out of 3 attempts alone computes
over 95% confidence against an established baseline, using nothing but
real math and an honest prior. A hard floor of 20 observations in
[src/detect/service.py](src/detect/service.py) runs *before* the
significance test is ever invoked — a required, independent safeguard, not
a redundant one, because the test genuinely cannot be trusted to reject
that sample on its own. Every cohort's evaluation is recorded in
`detector_runs` regardless of outcome — gated, not significant, or fired —
so a correctly suppressed false alarm is exactly as visible afterward as
one that actually fires.

---

## UI

Four screens, no more — a full React + TypeScript + Vite single-page app in
`web/`, over a small read-only FastAPI layer in `src/api/`
([schemas.py](src/api/schemas.py), [triage.py](src/api/triage.py),
[decisions.py](src/api/decisions.py), [ledger.py](src/api/ledger.py),
[results.py](src/api/results.py)). Every one of those routes only accepts
GET — enforced in [main.py](src/api/main.py)'s CORS policy, not just by
convention — because this UI only ever observes the system. Every
write-capable action still goes through
[src/policy/engine.py](src/policy/engine.py) and
[src/execute/outbox.py](src/execute/outbox.py), completely unchanged by
this stage.

| Screen | What it shows |
|:--|:--|
| **Live Triage** | Recent payments and whatever the system most recently decided about each — category, authorized intervention, whether it came from the rules table or the LLM, outbox status. Polls every 15s. |
| **Decision Detail** | One decision's full rule trace: what was proposed, what was authorized, whether it was overridden and by which `rule_id`, plus the LLM diagnosis behind it (if any) and the exact ledger entries recorded for it. Reached by clicking a decision in Live Triage. |
| **Audit Ledger** | The hash-chained log, paginated newest-first, each entry expandable to its full payload and hashes — with `verify_chain()` (Stage 1) run on demand, not merely asserted. |
| **Results** | The last committed `make eval` run: incremental lift with its confidence interval, the treatment/control comparison table, wasted-attempt rate, blocked actions by rule, and the stopping-rule/double-charge invariant counts. |

Run both halves side by side:

```bash
make run    # FastAPI on :8000
make web    # Vite dev server on :5173, proxying /api/* to :8000
```

---

## Status

All 10 stages are built and verified. `FAILURES.md` and the submission
recording capture the build in the team's own words — a suggested
walkthrough for the recording is prepared in
[docs/demo_script.md](docs/demo_script.md).

| Stage | Deliverable | Status |
|:--|:--|:--|
| 0 | Foundation: scaffold, Postgres, task runner, docs | ✅ |
| 1 | Schema + append-only hash-chained audit ledger | ✅ |
| 2 | Webhook ingress: HMAC verify, dedupe, state machine | ✅ |
| 3 | Canonical failure taxonomy + deterministic classifier | ✅ |
| 4 | Policy engine, intervention catalog, stopping rules | ✅ |
| 5 | Razorpay execution: outbox, idempotency, breaker | ✅ |
| 6 | Evaluation harness with randomised control arm | ✅ |
| 7 | LLM layer: long-tail classifier + diagnosis | ✅ |
| 8 | Statistical degradation detector | ✅ |
| 9 | UI: triage, decision detail, audit ledger, results | ✅ |
| 10 | Documentation, evidence, demo | 🟡 README/EVALUATION.md finalised; `FAILURES.md` and the recording still to come |

The LLM arrives at stage 7 of 10, deliberately. See
[ADR-001](DECISIONS.md#adr-001--build-the-guardrails-before-the-model).

---

## Running it

Requires Docker Desktop and Python 3.13.

```bash
git clone https://github.com/manoharreddydaram/retryable.git
cd retryable

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env

make db-up                         # Windows: .\tasks.ps1 db-up
make migrate                       # Windows: .\tasks.ps1 migrate
make run                           # Windows: .\tasks.ps1 run

# In a second terminal, for the UI:
make web-install                   # Windows: .\tasks.ps1 web-install (once)
make web                           # Windows: .\tasks.ps1 web
```

`make` is the canonical interface. Windows users can substitute
`.\tasks.ps1 <task>` for `make <task>` throughout. The UI needs Node.js 20+
in addition to Python 3.13.

---

## Repository map

| Path | Contents |
|:--|:--|
| `policies/` | Decision rules and the intervention catalog, as versioned YAML |
| `eval/` | Batch generator, payer simulator, evaluation runner |
| `eval/results/` | Committed evaluation output — the evidence behind every number |
| `prompts/` | Versioned LLM prompts, hashed and recorded on each diagnosis |
| `src/detect/` | Statistical degradation detection: EWMA baseline, beta-binomial test. No LLM. |
| `src/diagnose/` | Evidence bundling, the LLM call, citation validation. Proposes only. |
| `src/policy/` | The decision engine. The only code that may authorise spend. |
| `src/ledger/` | Append-only, hash-chained audit log |
| `src/api/` | The read API. Every route is GET — this layer never authorises anything. |
| `web/` | The Stage 9 UI: React + TypeScript + Vite, four screens, no more |
| `DECISIONS.md` | Architecture decision records |
| `FAILURES.md` | What broke during the build, and how it was fixed |
| `EVALUATION.md` | Methodology, and an honest account of what is simulated |
| `docs/demo_script.md` | Submission-recording walkthrough, grounded in real evidence already in the database |

`policies/` and `eval/` sit at the top level alongside `src/` on purpose. The
decision rules and the evidence are first-class artifacts of this project, not
implementation details.

---

## Documentation

- [DECISIONS.md](DECISIONS.md) — why the architecture looks like this
- [FAILURES.md](FAILURES.md) — what broke, and how we got out
- [EVALUATION.md](EVALUATION.md) — how the numbers were produced
- [docs/demo_script.md](docs/demo_script.md) — walkthrough for the submission recording
