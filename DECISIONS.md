# Architecture Decision Records

Short records of choices a reviewer might reasonably question. Each one states
what we chose, what we gave up, and why the trade was worth it.

---

## ADR-001 — Build the guardrails before the model

**Stage:** 0 · **Status:** Accepted

**Context.** The instinct is to build the interesting part first: the LLM that
diagnoses a payment failure. We are building it at stage 7 of 10 instead.

**Decision.** Ship the audit ledger, the deterministic classifier, the policy
engine, the execution layer with idempotency, and the evaluation harness
*before* any LLM code exists.

**Consequences.**
- After Stage 6 the project is submittable with zero AI. The deadline risk is
  carried by the least valuable component rather than the most.
- The LLM is forced to fit constraints that already exist, rather than the
  constraints being retrofitted around whatever the model happens to do.
- We can measure precisely what the LLM adds, because the rules-only baseline
  is a real running system rather than a hypothetical.

---

## ADR-002 — No agent framework

**Stage:** 0 · **Status:** Accepted

**Context.** LangChain, CrewAI and similar frameworks are the default choice for
LLM projects, and multi-agent architecture diagrams are common in hackathon
submissions.

**Decision.** Call the Anthropic SDK directly. No orchestration framework.

**Rationale.** This system is a fixed pipeline — ingest, classify, diagnose,
decide, execute, measure — with exactly one genuinely uncertain step. An agent
framework introduces non-determinism into a workflow whose entire value
proposition is that money decisions are reproducible and auditable. We would be
trading auditability for nothing.

**Consequences.** More code written by hand. In exchange, every LLM call is a
plain function with a schema-validated return value that can be unit tested,
and there is no hidden control flow between a model's output and a payment API.

---

## ADR-003 — Transactional outbox instead of a task queue

**Stage:** 0 · **Status:** Accepted

**Context.** Background work — dispatching recovery actions to Razorpay — is
usually handled with Celery plus Redis.

**Decision.** Use a Postgres-backed transactional outbox with a polling
dispatcher using `SELECT ... FOR UPDATE SKIP LOCKED`.

**Rationale.** The failure mode we care most about is a database write and an
external API call diverging: the decision is recorded but the call never
happens, or the call happens but the record is lost. An outbox writes the
decision and the intent to act in the **same transaction**, so they cannot
diverge. A separate queue reintroduces exactly the gap we are trying to close.
It is also two fewer services for a reviewer to install.

**Consequences.** Slightly higher dispatch latency from polling. Irrelevant at
our volumes, and the reliability property is the point of the project.

---

## ADR-004 — Money is stored as integer paise

**Stage:** 0 · **Status:** Accepted

**Context.** Floating point representation of currency accumulates error.

**Decision.** All amounts are Python `int`, denominated in paise, end to end.
This matches Razorpay's own API convention, so no conversion is needed at the
boundary.

**Consequences.** Display formatting is a presentation concern only. No
arithmetic anywhere in this codebase operates on a float amount.

---

## ADR-005 — Exact beta-binomial integration over a frequentist z-test

**Stage:** 8 · **Status:** Accepted

**Context.** The degradation detector needs to decide whether a cohort's
recent failure rate is genuinely worse than its baseline, or just noise.
CLAUDE.md names the tool explicitly — EWMA for the baseline, a
beta-binomial significance test for the decision — ruling out an LLM here
on the same grounds as detecting degradation generally: this is a
statistics problem, not a language problem. The obvious alternative
implementation is a two-proportion z-test using a normal approximation.

**Decision.** Model the baseline as a Beta distribution (its EWMA-tracked
rate, scaled by a fixed pseudo-sample-size standing in for how much that
baseline is trusted) and the recent window as a second Beta distribution (a
flat prior updated by the window's real counts). Compute
P(recent rate > baseline rate) by exact numerical integration
(`scipy.integrate.quad`) of one posterior's density against the other's
CDF — not Monte Carlo sampling.

**Rationale.** A normal approximation degrades exactly where this system
needs it most: small samples and rates near 0% or 100%, which describes
most per-category cohorts most of the time (e.g. `instrument_blocked`
failures are a small minority of all failures under normal conditions).
The beta-binomial comparison stays well-defined at any sample size and
returns an exact probability rather than a p-value that leans on an
approximation known to be shaky in the exact regime this project is
protecting against. Choosing exact integration over Monte Carlo sampling
removes a random seed from the decision path entirely: the same four
numbers in always produce the same probability out, with no sampling noise
to reason about at all.

**Consequences.** `tests/test_detect_significance.py` asserts fixed
numerical bounds rather than tolerating run-to-run variance. The test alone
is demonstrably not sufficient to prevent false alarms on tiny samples —
`test_tiny_sample_alone_is_not_a_safe_gate` shows 2 failures out of 3
attempts alone producing over 95% confidence against an established
baseline. The hard minimum-sample floor in `src/detect/service.py` is
therefore a required, independent safeguard, not a redundant one on top of
an already-conservative test.
