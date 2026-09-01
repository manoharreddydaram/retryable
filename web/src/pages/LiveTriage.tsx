import { Link } from 'react-router-dom'
import { apiGet } from '../api/client'
import { Badge } from '../components/Badge'
import { useApi } from '../hooks/useApi'
import { formatDateTime, formatPaise } from '../lib/format'
import type { TriageRow } from '../types'

function interventionTone(row: TriageRow): 'neutral' | 'green' | 'red' | 'amber' {
  if (!row.authorized_intervention) return 'neutral'
  if (row.overridden) return 'amber'
  if (row.authorized_intervention === 'suppress') return 'red'
  return 'green'
}

export function LiveTriage() {
  const { data, loading, error, reload } = useApi(() => apiGet<TriageRow[]>('/api/triage'), [], {
    pollMs: 15000,
  })

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Live Triage</h1>
          <p className="mt-1 text-sm text-slate-400">
            Recent payments and what the system decided about each. Refreshes automatically every
            15s.
          </p>
        </div>
        <button
          onClick={reload}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Refresh
        </button>
      </div>

      {error && <p className="text-sm text-rose-400">Couldn't load triage data: {error}</p>}
      {loading && !data && <p className="text-sm text-slate-500">Loading…</p>}
      {data && data.length === 0 && <p className="text-sm text-slate-500">No payments recorded yet.</p>}

      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-900/60 text-left text-xs tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-3">Order</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Category</th>
                <th className="px-4 py-3">Decision</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Outbox</th>
                <th className="px-4 py-3">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {data.map((row) => (
                <tr key={row.order_id} className="hover:bg-slate-900/40">
                  <td className="px-4 py-3 font-mono text-xs text-slate-300">{row.order_id}</td>
                  <td className="px-4 py-3">
                    <Badge tone={row.status === 'failed' ? 'red' : 'green'}>{row.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{formatPaise(row.amount_paise)}</td>
                  <td className="px-4 py-3 text-slate-400">{row.category ?? '—'}</td>
                  <td className="px-4 py-3">
                    {row.decision_id ? (
                      <Link to={`/decisions/${row.decision_id}`} className="hover:underline">
                        <Badge tone={interventionTone(row)}>{row.authorized_intervention}</Badge>
                      </Link>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {row.decision_id ? (
                      <Badge tone={row.via_llm ? 'purple' : 'neutral'}>
                        {row.via_llm ? 'LLM' : 'rules'}
                      </Badge>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-400">{row.outbox_status ?? '—'}</td>
                  <td className="px-4 py-3 text-slate-500">{formatDateTime(row.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
