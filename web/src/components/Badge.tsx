import type { ReactNode } from 'react'

type Tone = 'neutral' | 'green' | 'red' | 'amber' | 'purple' | 'blue'

const TONES: Record<Tone, string> = {
  neutral: 'bg-slate-700/60 text-slate-200',
  green: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30',
  red: 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/30',
  amber: 'bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30',
  purple: 'bg-violet-500/15 text-violet-400 ring-1 ring-violet-500/30',
  blue: 'bg-sky-500/15 text-sky-400 ring-1 ring-sky-500/30',
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  )
}
