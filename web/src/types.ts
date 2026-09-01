// Mirrors src/api/schemas.py. Kept as plain interfaces, not generated --
// there are four screens and one backend in this project; a codegen step
// would be more machinery than the surface it's covering.

export interface TriageRow {
  order_id: string
  status: string
  amount_paise: number
  method: string | null
  error_reason: string | null
  category: string | null
  updated_at: string
  decision_id: string | null
  authorized_intervention: string | null
  overridden: boolean | null
  rule_id: string | null
  via_llm: boolean
  outbox_status: string | null
}

export interface PaymentSummary {
  order_id: string
  status: string
  method: string | null
  currency: string
  error_code: string | null
  error_reason: string | null
}

export interface DiagnosisDetail {
  id: string
  prompt_version: string
  prompt_hash: string
  model: string
  reasoning: string | null
  cited_evidence_ids: string[] | null
  evidence_bundle: { items?: { id: string; description: string }[] }
  suggested_intervention: string | null
  created_at: string
}

export interface OutboxSummary {
  status: string
  attempts: number
  last_error: string | null
  razorpay_short_url: string | null
  next_attempt_at: string
  updated_at: string
}

export interface LedgerEntrySummary {
  seq: number
  entry_id: string
  created_at: string
  entity_type: string
  entity_id: string
  event_type: string
  actor: string
  payload: Record<string, unknown>
  prev_hash: string
  this_hash: string
}

export interface DecisionDetailResponse {
  id: string
  order_id: string
  payer_contact: string | null
  category: string
  confidence: number
  amount_paise: number
  proposed_intervention: string
  authorized_intervention: string
  overridden: boolean
  rule_id: string
  reason: string
  retry_at: string | null
  decided_at: string
  payment: PaymentSummary
  diagnosis: DiagnosisDetail | null
  outbox: OutboxSummary | null
  ledger_entries: LedgerEntrySummary[]
}

export interface LedgerPage {
  entries: LedgerEntrySummary[]
  next_before_seq: number | null
}

export interface ChainVerification {
  valid: boolean
  entries_checked: number
  first_broken_seq: number | null
  reason: string | null
}

export interface ArmMetrics {
  revenue_at_risk_paise: number
  attempted_sends: number
  converted_sends: number
  gross_recovered_paise: number
  gross_recovery_rate: number
  wasted_attempt_rate: number
}

export interface EvalResultsResponse {
  generated_at: string
  seed: number
  batch_size: number
  treatment: ArmMetrics
  control: ArmMetrics
  incremental_lift: number
  incremental_lift_ci95: [number, number]
  intervention_cost_paise: number
  net_recovered_paise: number
  cost_per_recovered_rupee: number
  blocked_actions: Record<string, number>
  unresolved_exceptions: number
  stopping_rule_violations: number
  double_charge_incidents: number
  known_reason_accuracy: number
  novel_string_accuracy: number
  pending_not_yet_dispatched: number
}
