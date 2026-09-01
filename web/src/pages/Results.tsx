import { apiGet } from '../api/client'
import { useApi } from '../hooks/useApi'
import { formatDateTime, formatPaise, formatPercent } from '../lib/format'
import type { EvalResultsResponse } from '../types'

export function Results() {
  const { data, loading, error } = useApi(
    () => apiGet<EvalResultsResponse>('/api/results/latest'),
    [],
  )

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <h1 className="text-xl font-semibold text-slate-100">Results</h1>
      <p className="mt-1 text-sm text-slate-400">
        The last committed <code className="text-slate-300">make eval</code> run — treatment vs. a
        naive fixed-retry control, both dispatched through the same real pipeline.
      </p>

      {error && (
        <p className="mt-4 text-sm text-rose-400">
          {error.includes('no_eval_results_yet')
            ? 'No eval run has been committed yet — run `make eval`.'
            : `Couldn't load results: ${error}`}
        </p>
      )}
      {loading && !data && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && (
        <div className="mt-6 space-y-6">
          <div className="text-xs text-slate-500">
            seed={data.seed} · batch_size={data.batch_size} · generated{' '}
            {formatDateTime(data.generated_at)}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard
              label="Incremental lift"
              value={formatPercent(data.incremental_lift)}
              sub={`95% CI [${formatPercent(data.incremental_lift_ci95[0])}, ${formatPercent(data.incremental_lift_ci95[1])}]`}
            />
            <StatCard
              label="Net recovered"
              value={formatPaise(data.net_recovered_paise)}
              sub={`${formatPaise(data.intervention_cost_paise)} per attempt`}
            />
            <StatCard
              label="Cost per recovered rupee"
              value={`₹${data.cost_per_recovered_rupee.toFixed(3)}`}
            />
          </div>

          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-900/60 text-left text-xs tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-3"></th>
                  <th className="px-4 py-3">Treatment</th>
                  <th className="px-4 py-3">Control</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-200">
                <Row
                  label="Revenue at risk"
                  t={formatPaise(data.treatment.revenue_at_risk_paise)}
                  c={formatPaise(data.control.revenue_at_risk_paise)}
                />
                <Row
                  label="Attempted sends"
                  t={data.treatment.attempted_sends}
                  c={data.control.attempted_sends}
                />
                <Row
                  label="Converted"
                  t={data.treatment.converted_sends}
                  c={data.control.converted_sends}
                />
                <Row
                  label="Gross recovered"
                  t={formatPaise(data.treatment.gross_recovered_paise)}
                  c={formatPaise(data.control.gross_recovered_paise)}
                />
                <Row
                  label="Gross recovery rate"
                  t={formatPercent(data.treatment.gross_recovery_rate)}
                  c={formatPercent(data.control.gross_recovery_rate)}
                />
                <Row
                  label="Wasted-attempt rate"
                  t={formatPercent(data.treatment.wasted_attempt_rate)}
                  c={formatPercent(data.control.wasted_attempt_rate)}
                />
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Known-reason accuracy" value={formatPercent(data.known_reason_accuracy)} />
            <StatCard
              label="Novel-string accuracy"
              value={formatPercent(data.novel_string_accuracy)}
            />
            <StatCard
              label="Stopping-rule violations"
              value={String(data.stopping_rule_violations)}
              alert={data.stopping_rule_violations > 0}
            />
            <StatCard
              label="Double-charge incidents"
              value={String(data.double_charge_incidents)}
              alert={data.double_charge_incidents > 0}
            />
          </div>

          <div>
            <h2 className="text-sm font-semibold tracking-wide text-slate-400 uppercase">
              Blocked actions
            </h2>
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(data.blocked_actions).map(([rule, count]) => (
                <span key={rule} className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300">
                  {rule}: {count}
                </span>
              ))}
              {Object.keys(data.blocked_actions).length === 0 && (
                <span className="text-sm text-slate-500">None.</span>
              )}
            </div>
          </div>

          {data.pending_not_yet_dispatched > 0 && (
            <p className="text-sm text-amber-400">
              {data.pending_not_yet_dispatched} entries were still pending dispatch when this run's
              metrics were computed (e.g. Razorpay rate limiting) — see EVALUATION.md.
            </p>
          )}

          <p className="text-sm text-slate-500">
            {data.unresolved_exceptions} unresolved exceptions routed to a human.
          </p>
        </div>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  sub,
  alert,
}: {
  label: string
  value: string
  sub?: string
  alert?: boolean
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${alert ? 'border-rose-900/50 bg-rose-950/10' : 'border-slate-800 bg-slate-900/40'}`}
    >
      <div className="text-xs tracking-wide text-slate-500 uppercase">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${alert ? 'text-rose-400' : 'text-slate-100'}`}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

function Row({ label, t, c }: { label: string; t: string | number; c: string | number }) {
  return (
    <tr>
      <td className="px-4 py-3 text-slate-400">{label}</td>
      <td className="px-4 py-3">{t}</td>
      <td className="px-4 py-3">{c}</td>
    </tr>
  )
}
