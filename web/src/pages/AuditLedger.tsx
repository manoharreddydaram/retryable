import { useState } from 'react'
import { apiGet } from '../api/client'
import { Badge } from '../components/Badge'
import { useApi } from '../hooks/useApi'
import { formatDateTime } from '../lib/format'
import type { ChainVerification, LedgerPage } from '../types'

const PAGE_START = Number.MAX_SAFE_INTEGER

export function AuditLedger() {
  const [beforeSeq, setBeforeSeq] = useState<number | undefined>(undefined)
  const [history, setHistory] = useState<number[]>([])

  const page = useApi(
    () =>
      apiGet<LedgerPage>(
        `/api/ledger?limit=25${beforeSeq !== undefined ? `&before_seq=${beforeSeq}` : ''}`,
      ),
    [beforeSeq],
  )
  const verification = useApi(() => apiGet<ChainVerification>('/api/ledger/verify'), [])

  function nextPage() {
    if (page.data?.next_before_seq == null) return
    setHistory((h) => [...h, beforeSeq ?? PAGE_START])
    setBeforeSeq(page.data.next_before_seq)
  }

  function prevPage() {
    setHistory((h) => {
      const copy = [...h]
      const prev = copy.pop()
      setBeforeSeq(prev === PAGE_START ? undefined : prev)
      return copy
    })
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Audit Ledger</h1>
          <p className="mt-1 text-sm text-slate-400">
            Append-only, hash-chained record of every consequential event.
          </p>
        </div>
        {verification.data && (
          <Badge tone={verification.data.valid ? 'green' : 'red'}>
            {verification.data.valid
              ? `Chain verified · ${verification.data.entries_checked} entries`
              : `Chain broken at seq ${verification.data.first_broken_seq}`}
          </Badge>
        )}
      </div>

      {page.error && <p className="text-sm text-rose-400">Couldn't load the ledger: {page.error}</p>}
      {page.loading && !page.data && <p className="text-sm text-slate-500">Loading…</p>}
      {page.data && page.data.entries.length === 0 && (
        <p className="text-sm text-slate-500">No ledger entries yet.</p>
      )}

      {page.data && page.data.entries.length > 0 && (
        <>
          <div className="space-y-2">
            {page.data.entries.map((entry) => (
              <details
                key={entry.entry_id}
                className="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
              >
                <summary className="flex cursor-pointer items-center justify-between text-sm">
                  <span className="flex items-center gap-3">
                    <span className="font-mono text-slate-500">#{entry.seq}</span>
                    <span className="text-slate-200">{entry.event_type}</span>
                    <span className="text-slate-500">
                      {entry.entity_type}:{entry.entity_id}
                    </span>
                  </span>
                  <span className="text-slate-500">{formatDateTime(entry.created_at)}</span>
                </summary>
                <div className="mt-3 space-y-2 text-xs">
                  <div className="text-slate-500">
                    actor: <span className="text-slate-300">{entry.actor}</span>
                  </div>
                  <div className="font-mono break-all text-slate-600">prev {entry.prev_hash}</div>
                  <div className="font-mono break-all text-slate-600">this {entry.this_hash}</div>
                  <pre className="overflow-x-auto rounded bg-slate-950 p-3 text-slate-300">
                    {JSON.stringify(entry.payload, null, 2)}
                  </pre>
                </div>
              </details>
            ))}
          </div>

          <div className="mt-6 flex justify-between">
            <button
              onClick={prevPage}
              disabled={history.length === 0}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-30"
            >
              ← Newer
            </button>
            <button
              onClick={nextPage}
              disabled={page.data.next_before_seq == null}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-30"
            >
              Older →
            </button>
          </div>
        </>
      )}
    </div>
  )
}
