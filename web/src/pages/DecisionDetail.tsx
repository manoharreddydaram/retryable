import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiGet } from '../api/client'
import { Badge } from '../components/Badge'
import { useApi } from '../hooks/useApi'
import { formatDateTime, formatPaise } from '../lib/format'
import type { DecisionDetailResponse } from '../types'

export function DecisionDetail() {
  const { decisionId } = useParams<{ decisionId: string }>()
  const { data, loading, error } = useApi(
    () => apiGet<DecisionDetailResponse>(`/api/decisions/${decisionId}`),
    [decisionId],
  )

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
        ← Back to Live Triage
      </Link>

      {error && <p className="mt-4 text-sm text-rose-400">Couldn't load this decision: {error}</p>}
      {loading && !data && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && (
        <div className="mt-4 space-y-6">
          <div>
            <h1 className="text-xl font-semibold text-slate-100">Decision for {data.order_id}</h1>
            <p className="mt-1 font-mono text-xs text-slate-500">{data.id}</p>
          </div>

          <Section title="Rule trace">
            <Field label="Proposed">{data.proposed_intervention}</Field>
            <Field label="Authorized">
              <Badge tone={data.overridden ? 'amber' : 'green'}>{data.authorized_intervention}</Badge>
            </Field>
            <Field label="Overridden">{data.overridden ? 'Yes' : 'No'}</Field>
            <Field label="Rule ID">
              <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-200">
                {data.rule_id}
              </code>
            </Field>
            <Field label="Reason" full>
              {data.reason}
            </Field>
            {data.retry_at && <Field label="Retry at">{formatDateTime(data.retry_at)}</Field>}
            <Field label="Decided at">{formatDateTime(data.decided_at)}</Field>
          </Section>

          <Section title="Classification">
            <Field label="Category">{data.category}</Field>
            <Field label="Confidence">{(data.confidence * 100).toFixed(0)}%</Field>
            <Field label="Amount">{formatPaise(data.amount_paise)}</Field>
            <Field label="Source">
              <Badge tone={data.diagnosis ? 'purple' : 'neutral'}>
                {data.diagnosis ? 'LLM diagnosis' : 'deterministic rules'}
              </Badge>
            </Field>
          </Section>

          <Section title="Payment">
            <Field label="Status">{data.payment.status}</Field>
            <Field label="Method">{data.payment.method ?? '—'}</Field>
            <Field label="Error code">{data.payment.error_code ?? '—'}</Field>
            <Field label="Error reason">{data.payment.error_reason ?? '—'}</Field>
          </Section>

          {data.diagnosis && (
            <section className="rounded-lg border border-violet-900/40 bg-violet-950/10 p-5">
              <h2 className="text-sm font-semibold tracking-wide text-violet-400 uppercase">
                LLM diagnosis
              </h2>
              <dl className="mt-3 grid grid-cols-2 gap-4 text-sm">
                <Field label="Model">{data.diagnosis.model}</Field>
                <Field label="Prompt">
                  {data.diagnosis.prompt_version} ({data.diagnosis.prompt_hash.slice(0, 12)}…)
                </Field>
                <Field label="Suggested intervention" full>
                  {data.diagnosis.suggested_intervention}
                </Field>
                <Field label="Reasoning" full>
                  {data.diagnosis.reasoning}
                </Field>
                <Field label="Cited evidence" full>
                  <ul className="list-disc space-y-1 pl-5 text-slate-300">
                    {data.diagnosis.cited_evidence_ids?.map((id) => {
                      const item = data.diagnosis?.evidence_bundle.items?.find((i) => i.id === id)
                      return <li key={id}>{item ? `[${id}] ${item.description}` : id}</li>
                    })}
                  </ul>
                </Field>
              </dl>
            </section>
          )}

          {data.outbox && (
            <Section title="Execution">
              <Field label="Status">{data.outbox.status}</Field>
              <Field label="Attempts">{data.outbox.attempts}</Field>
              {data.outbox.razorpay_short_url && (
                <Field label="Payment link" full>
                  <a
                    href={data.outbox.razorpay_short_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sky-400 hover:underline"
                  >
                    {data.outbox.razorpay_short_url}
                  </a>
                </Field>
              )}
              {data.outbox.last_error && (
                <Field label="Last error" full>
                  {data.outbox.last_error}
                </Field>
              )}
            </Section>
          )}

          <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
            <h2 className="text-sm font-semibold tracking-wide text-slate-400 uppercase">
              Ledger entries ({data.ledger_entries.length})
            </h2>
            <div className="mt-3 space-y-2">
              {data.ledger_entries.map((entry) => (
                <div key={entry.entry_id} className="rounded border border-slate-800 p-3 text-xs">
                  <div className="flex justify-between text-slate-400">
                    <span>{entry.event_type}</span>
                    <span>{formatDateTime(entry.created_at)}</span>
                  </div>
                  <div className="mt-1 font-mono text-slate-600">
                    seq {entry.seq} · {entry.this_hash.slice(0, 16)}…
                  </div>
                </div>
              ))}
              {data.ledger_entries.length === 0 && (
                <p className="text-sm text-slate-500">No ledger entries for this decision.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="text-sm font-semibold tracking-wide text-slate-400 uppercase">{title}</h2>
      <dl className="mt-3 grid grid-cols-2 gap-4 text-sm">{children}</dl>
    </section>
  )
}

function Field({ label, children, full }: { label: string; children: ReactNode; full?: boolean }) {
  return (
    <div className={full ? 'col-span-2' : undefined}>
      <dt className="text-xs tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-0.5 text-slate-200">{children}</dd>
    </div>
  )
}
