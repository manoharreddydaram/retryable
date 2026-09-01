# Evaluation methodology

Written in Stage 0, before any results exist, so that the method is fixed in
advance rather than chosen after seeing the numbers.

---

## The honest boundary

This system runs against Razorpay **test mode**. Test mode has no real
customers, so no real customer can decide to pay. Any project in this track
that claims a real-world recovery uplift is claiming something it cannot have
measured. We are not going to do that.

### What is real

- Razorpay test-mode API calls, and their real latency and error behaviour
- Webhook delivery, HMAC signature verification, duplicate and out-of-order handling
- Payment link creation, idempotency keys, retry and circuit-breaker behaviour
- The degradation detector, the classifier, the policy engine, the audit ledger
- Root-cause classification accuracy against held-out ground truth
- Throughput, latency, API error rates, blocked-action counts

### What is simulated, and declared as such

**Customer willingness to pay.** A payer-response simulator assigns each cohort
a probability of converting given (cohort, channel, timing, attempt number).

Three constraints keep this honest:

1. The propensity table is **committed to git before the evaluation is run**.
   It cannot be tuned after seeing a disappointing result.
2. The values are **sourced from published dunning and payment-recovery
   benchmarks**, cited inline in the table.
3. The simulator is **blind to the agent's reasoning**. It never sees the
   diagnosis, the confidence score, or the rule that fired. It sees only the
   cohort and the shape of the attempt.

The simulator is therefore incapable of flattering our decisions. It can only
reward us for putting the right cohorts into the right treatment at the right
time — which is the thing under test.

---

## Experimental design

A batch of failed payments is split by a **seeded randomisation** into two arms:

| Arm | Share | Treatment |
|:--|:--|:--|
| Control | 30% | Naive fixed baseline: retry once, one hour later, regardless of cause |
| Treatment | 70% | Full pipeline: diagnose, decide, bounded intervention or deliberate silence |

The control arm is deliberately not "do nothing." It is the product most
competing submissions will build. Measuring against *nothing* would flatter us;
measuring against *the obvious approach* is the comparison that means something.

**We report incremental lift, never gross recovery.**

---

## Metrics

| Metric | Definition |
|:--|:--|
| Revenue at risk | Σ amount of failed payments in the batch, in paise |
| Gross recovery rate | converted sends / attempted sends, per arm |
| **Incremental lift** | treatment recovery rate − control recovery rate, with a 95% CI |
| Net recovered | ₹ recovered − intervention cost, across both arms |
| Cost per recovered rupee | total intervention cost / amount recovered |
| **Wasted-attempt rate** | (attempted − converted) / attempted, per arm |
| Known-reason accuracy | accuracy on error strings the rules table has seen before |
| Novel-string accuracy | for a genuinely novel error string, whether the classifier honestly reports `unknown` rather than guessing wrong |
| Stopping-rule violations | payers contacted more than the touch cap allows, checked directly against executed sends — **must be 0** |
| Blocked actions | policy vetoes, with the rule ID for each |
| Double-charge incidents | more than one completed send for the same order — **must be 0** |
| Unresolved exceptions | escalated to a human, or permanently failed dispatch |
| Pending, not yet dispatched | outbox entries still awaiting a dispatcher run when metrics were computed — surfaced explicitly so a partially-drained batch is never presented as fully measured |

Wasted-attempt rate is the direct measurement of false-positive cost. Every
intervention carries a rupee cost and a trust cost; a system that reports only
gross recovery is hiding half of its own P&L.

**Revised from the original plan, not silently swapped:** this section
originally called for a root-cause macro-F1 on a held-out set. Once Stage 3's
classifier was actually built, that turned out to be the wrong shape of
question for it: it's a deterministic lookup table, not a probabilistic
classifier making per-class tradeoffs, so a known error string is either
matched correctly or it isn't — there's no precision/recall balance to
average across classes. Known-reason accuracy and novel-string accuracy
(implemented in [eval/metrics.py](eval/metrics.py)) are the honest replacement:
the first is a sanity check expected at 1.0 by construction, and the second
is the one thing worth actually grading a lookup table on — does it admit
"unknown" for a string it has never seen, rather than guess.

---

## Reproducibility

Every number published in the README must be reproducible by a single command
(`make eval`, added in Stage 6), with a fixed random seed. Raw output is
committed to `eval/results/`.

---

## Known limitations

Stated up front rather than extracted under questioning:

1. **No real payer behaviour.** See above. The lift figure is a measure of
   decision quality under a stated behavioural model, not a market prediction.
2. **One acquirer's error vocabulary.** The classifier has seen Razorpay test
   mode only. Production would demand a labelled corpus across acquirers.
3. **No shadow-mode period.** A real deployment would run proposals past human
   review for weeks before being allowed to act.
4. **Synthetic batch composition.** Cohort mix is our estimate of a mid-market
   merchant's failure profile, not an observed distribution.
5. **`make eval` does not exercise Stage 7's LLM diagnosis path.** Every
   synthetic `unknown`-category failure in a batch stays `unknown` for the
   purposes of these metrics — it is never sent to Claude for a second look,
   by design: re-diagnosis is a separate, on-demand pass
   (`make diagnose`, see the README's LLM layer section), not part of the
   ingest-time path `run_evaluation()` drives. The incremental-lift figure
   above is therefore the rules-only baseline's lift, not a measurement of
   what the LLM adds. Quantifying that would need a batch run through
   `make diagnose` before metrics are computed — a natural extension, not
   yet built.
