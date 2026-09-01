"""Pydantic response models for the Stage 9 read API.

Every model here is a projection of tables that already exist -- no new
business logic lives behind this module. GET is the only method any Stage 9
route accepts (enforced in main.py's CORS policy too): this UI observes the
system, it never authorises anything. Every write-capable action still goes
through src/policy/engine.py and src/execute/outbox.py, completely
unchanged by this stage.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TriageRow(BaseModel):
    order_id: str
    status: str
    amount_paise: int
    method: str | None
    error_reason: str | None
    category: str | None
    updated_at: datetime
    decision_id: UUID | None
    authorized_intervention: str | None
    overridden: bool | None
    rule_id: str | None
    via_llm: bool
    outbox_status: str | None


class PaymentSummary(BaseModel):
    order_id: str
    status: str
    method: str | None
    currency: str
    error_code: str | None
    error_reason: str | None


class DiagnosisDetail(BaseModel):
    id: UUID
    prompt_version: str
    prompt_hash: str
    model: str
    reasoning: str | None
    cited_evidence_ids: list[str] | None
    evidence_bundle: dict
    suggested_intervention: str | None
    created_at: datetime


class OutboxSummary(BaseModel):
    status: str
    attempts: int
    last_error: str | None
    razorpay_short_url: str | None
    next_attempt_at: datetime
    updated_at: datetime


class LedgerEntrySummary(BaseModel):
    seq: int
    entry_id: UUID
    created_at: datetime
    entity_type: str
    entity_id: str
    event_type: str
    actor: str
    payload: dict
    prev_hash: str
    this_hash: str


class DecisionDetailResponse(BaseModel):
    id: UUID
    order_id: str
    payer_contact: str | None
    category: str
    confidence: float
    amount_paise: int
    proposed_intervention: str
    authorized_intervention: str
    overridden: bool
    rule_id: str
    reason: str
    retry_at: datetime | None
    decided_at: datetime
    payment: PaymentSummary
    diagnosis: DiagnosisDetail | None
    outbox: OutboxSummary | None
    ledger_entries: list[LedgerEntrySummary]


class LedgerPage(BaseModel):
    entries: list[LedgerEntrySummary]
    next_before_seq: int | None


class ChainVerification(BaseModel):
    valid: bool
    entries_checked: int
    first_broken_seq: int | None
    reason: str | None


class ArmMetrics(BaseModel):
    revenue_at_risk_paise: int
    attempted_sends: int
    converted_sends: int
    gross_recovered_paise: int
    gross_recovery_rate: float
    wasted_attempt_rate: float


class EvalResultsResponse(BaseModel):
    generated_at: datetime
    seed: int
    batch_size: int
    treatment: ArmMetrics
    control: ArmMetrics
    incremental_lift: float
    incremental_lift_ci95: list[float]
    intervention_cost_paise: int
    net_recovered_paise: int
    cost_per_recovered_rupee: float
    blocked_actions: dict[str, int]
    unresolved_exceptions: int
    stopping_rule_violations: int
    double_charge_incidents: int
    known_reason_accuracy: float
    novel_string_accuracy: float
    # Defaulted, not required: eval/results/latest_run.json is committed
    # evidence that can predate a field write_results() has since started
    # producing (this one did) -- re-running `make eval` refreshes it, but
    # this endpoint reads whatever is actually committed right now.
    pending_not_yet_dispatched: int = 0
