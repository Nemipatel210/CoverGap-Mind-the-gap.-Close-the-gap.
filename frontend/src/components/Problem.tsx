import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, ShieldCheck } from 'lucide-react'
import { api, type Any } from '../api'
import { useRole } from '../App'
import { Badge, Button, useAction } from '../ui'

export const sevDot = (s: string) => (s === 'critical' ? 'bg-bad' : s === 'warning' ? 'bg-warn' : 'bg-navy-600/40')

export function Where({ w }: { w: Any }) {
  const parts = [w.hospital, w.consult, w.doctor].filter(Boolean)
  return <span className="text-sm text-ink-soft">{parts.join(' · ')}</span>
}

const toneFor = (state: string) =>
  ['accepted', 'authorized', 'alerted'].includes(state) ? 'ok'
    : ['declined', 'timed_out', 'rejected', 'plan_rejected', 'plan_failed'].includes(state) ? 'critical' : 'warning'

/** What has been done so far (plan sent, offer out, doctor joining...). */
export function StatusBadge({ p }: { p: Any }) {
  const nav = useNavigate()
  if (!p.status) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={toneFor(p.status.state) as Any}>{p.status.label}</Badge>
      {['split_shift', 'joining'].includes(p.fix.kind) && !String(p.status.state).startsWith('plan') &&
        <button className="text-xs font-medium text-teal-600" onClick={() => nav('/offers')}>Track offer</button>}
    </div>
  )
}

/** Compact action area for a list row: status, or a prompt to choose between the plans. */
export function FixAction({ p, onChoose }: { p: Any; onChoose?: () => void }) {
  const { role } = useRole()
  const open = !p.status || p.status.retry
  if (!open) return <StatusBadge p={p} />
  if (!p.plans?.length) return <span className="text-sm text-ink-soft">{p.fix.label}</span>
  if (role === 'clinical_lead') return <span className="text-sm text-ink-soft">Plan A: {p.plans[0].label}</span>
  return (
    <div className="flex flex-wrap items-center gap-2">
      {p.status?.retry && <StatusBadge p={p} />}
      <Button size="sm" variant="secondary" onClick={onChoose}>Choose a plan</Button>
    </div>
  )
}

/** Plan A (recommended) and Plan B side by side. The coordinator sends one to the clinical lead. */
export function PlanCards({ p, size = 'md' }: { p: Any; size?: 'md' | 'lg' }) {
  const { role, actor } = useRole()
  const { run, busy } = useAction()
  const canSend = role === 'coordinator' && (!p.status || p.status.retry)
  if (!p.plans?.length) return <p className="text-sm text-ink-soft">{p.fix.label}. {p.fix.why}</p>
  return (
    <div className={`grid gap-3 ${p.plans.length > 1 ? 'md:grid-cols-2' : ''}`}>
      {p.plans.map((pl: Any) => (
        <div key={pl.key} className={`flex flex-col rounded-xl border p-4 ${pl.recommended ? 'border-teal bg-teal-50/70' : 'border-line bg-white'}`}>
          <div className="flex items-center gap-2">
            <span className={`grid h-6 w-6 place-items-center rounded-full text-xs font-bold ${pl.recommended ? 'bg-teal text-white' : 'bg-navy-100 text-navy'}`}>{pl.key}</span>
            <span className="text-xs font-medium text-ink-soft">Plan {pl.key}{pl.recommended ? ' · recommended' : ''}</span>
          </div>
          <p className={`mt-2 font-semibold text-navy ${size === 'lg' ? 'text-base' : 'text-sm'}`}>{pl.label}</p>
          <p className="mt-1 text-sm">{pl.why}</p>
          {pl.kind === 'handoff' && pl.items?.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-ink-soft">
              {pl.items.map((x: Any) => <li key={x.consult_id}>{x.consult_id} ({x.stage}) {x.suggested ? <>→ {x.suggested}</> : '— nobody approved there stays longer'}</li>)}
            </ul>
          )}
          <p className="mt-2 text-xs text-ink-soft"><span className="font-medium text-ink">If approved: </span>{pl.effect}</p>
          {pl.kind === 'split_shift' && pl.incident_id && (
            <Link to={`/decide/${encodeURIComponent(pl.incident_id)}?for=${encodeURIComponent(p.id)}`} className="mt-1 text-xs font-medium text-teal-600">
              See everyone considered and why</Link>
          )}
          <div className="mt-auto pt-3">
            {canSend ? (
              <Button size={size === 'lg' ? 'md' : 'sm'} variant={pl.recommended ? 'primary' : 'secondary'} busy={busy === pl.key} className="w-full"
                onClick={() => run(pl.key, () => api.post(`/api/problems/${encodeURIComponent(p.id)}/plans`, { plan: pl.key, actor }), `Plan ${pl.key} sent to the clinical lead`)}>
                Send Plan {pl.key} for approval <ArrowRight className="h-4 w-4" />
              </Button>
            ) : <p className="flex items-center gap-1.5 text-xs text-ink-soft"><ShieldCheck className="h-3.5 w-3.5" />Needs clinical-lead approval</p>}
          </div>
        </div>
      ))}
    </div>
  )
}

/** Why it matters, then the plans. Used in the expanded list row and the lead view. */
export function ProblemDetail({ p }: { p: Any }) {
  return (
    <div className="space-y-4">
      <div>
        <h4 className="mb-1 text-xs font-semibold text-navy">Why it matters</h4>
        <ul className="list-disc space-y-1 pl-4 text-sm">{p.matters.map((m: string, i: number) => <li key={i}>{m}</li>)}</ul>
      </div>
      <div>
        <h4 className="mb-2 text-xs font-semibold text-navy">What to do</h4>
        {p.status && !p.status.retry ? <StatusBadge p={p} /> : <PlanCards p={p} />}
      </div>
    </div>
  )
}

export function ProblemRow({ p }: { p: Any }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="border-t border-line first:border-t-0">
      <div className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-3">
        <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-w-0 items-start gap-3 text-left sm:flex-1">
          <span className="num mt-0.5 w-5 shrink-0 text-right text-xs text-ink-faint">{p.rank}</span>
          <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${sevDot(p.severity)}`} aria-label={p.severity} />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{p.what}</span>
            <Where w={p.where} />
          </span>
        </button>
        <div className="flex flex-wrap items-center gap-2 pl-11 sm:shrink-0 sm:pl-0">
          {p.horizon !== 'now' && <Badge tone="neutral">in {p.horizon.replace('+', '')}</Badge>}
          <FixAction p={p} onChoose={() => setOpen(true)} />
        </div>
      </div>
      {open && <div className="bg-canvas/70 px-4 pb-4 pt-1 sm:pl-[3.25rem]"><ProblemDetail p={p} /></div>}
    </li>
  )
}
