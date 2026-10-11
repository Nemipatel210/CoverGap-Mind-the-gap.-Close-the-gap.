import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Any } from '../api'
import { useRole } from '../App'
import { Badge, Button, useAction } from '../ui'

export const sevDot = (s: string) => (s === 'critical' ? 'bg-bad' : s === 'warning' ? 'bg-warn' : 'bg-navy-600/40')

export function Where({ w }: { w: Any }) {
  const parts = [w.hospital, w.consult, w.doctor].filter(Boolean)
  return <span className="text-sm text-ink-soft">{parts.join(' · ')}</span>
}

/** The single action button for a problem, or its status once acted on. */
export function FixAction({ p, size = 'md', quiet }: { p: Any; size?: 'sm' | 'md' | 'lg'; quiet?: boolean }) {
  const { role, actor } = useRole()
  const nav = useNavigate()
  const { run, busy } = useAction()
  const f = p.fix
  const lead = role === 'clinical_lead'
  if (p.status) {
    const tone = ['accepted', 'authorized'].includes(p.status.state) ? 'ok' : ['declined', 'timed_out', 'rejected'].includes(p.status.state) ? 'critical' : 'warning'
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone as Any}>{p.status.label}</Badge>
        {['split_shift', 'joining'].includes(f.kind) && <button className="text-xs font-medium text-teal-600" onClick={() => nav('/offers')}>Track offer</button>}
      </div>
    )
  }
  if (f.kind === 'monitor' || f.kind === 'covered') return <span className="text-sm text-ink-soft">{f.label}</span>
  if (lead) return <span className="text-sm text-ink-soft">Proposed: {f.label}</span>
  const go = () => {
    if (f.kind === 'assign') return run('fix', () => api.post(`/api/consults/${p.where.consult}/reassign`, { physician_id: f.target_physician_id, actor }), `${p.where.consult} assigned`)
    if (f.kind === 'split_shift') return nav(`/decide/${encodeURIComponent(f.incident_id)}?for=${encodeURIComponent(p.id)}`)
    if (f.kind === 'escalate') return run('fix', () => api.post(`/api/problems/${encodeURIComponent(p.id)}/escalate`, { actor }), 'Escalated to the clinical lead')
    if (f.kind === 'alert') return run('fix', () => api.post(`/api/problems/${encodeURIComponent(p.id)}/alert`, { actor }), 'Internal alert sent')
  }
  if (f.kind === 'handoff') return null
  return <Button size={size} variant={quiet ? 'secondary' : 'primary'} busy={busy === 'fix'} onClick={go}>{f.label}</Button>
}

export function HandoffList({ p }: { p: Any }) {
  const { role, actor } = useRole()
  const { run, busy } = useAction()
  if (p.fix.kind !== 'handoff' || p.status) return null
  return (
    <ul className="space-y-1.5">
      {p.fix.items.map((x: Any) => (
        <li key={x.consult_id} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="num font-medium">{x.consult_id}</span>
          <span className="text-ink-soft">{x.stage} · {x.hospital_name}</span>
          {x.suggested ? (role === 'coordinator' ? (
            <Button size="sm" variant="secondary" busy={busy === x.consult_id} className="ml-auto"
              onClick={() => run(x.consult_id, () => api.post(`/api/consults/${x.consult_id}/reassign`, { physician_id: x.suggested_id, actor }), `${x.consult_id} handed to ${x.suggested}`)}>
              Hand to {x.suggested}</Button>) : <span className="ml-auto">→ {x.suggested}</span>)
            : <span className="ml-auto text-xs text-warn">Nobody approved there stays longer; finish before leaving</span>}
        </li>
      ))}
    </ul>
  )
}

/** Why it matters / what to do, used in the expanded list row and the lead view. */
export function ProblemDetail({ p }: { p: Any }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h4 className="mb-1 text-xs font-semibold text-navy">Why it matters</h4>
        <ul className="list-disc space-y-1 pl-4 text-sm">{p.matters.map((m: string, i: number) => <li key={i}>{m}</li>)}</ul>
      </div>
      <div>
        <h4 className="mb-1 text-xs font-semibold text-navy">What to do</h4>
        <p className="text-sm"><span className="font-medium">{p.fix.label}.</span> {p.fix.why}</p>
        {p.fix.approver !== '—' && <p className="mt-1 text-xs text-ink-soft">Who approves: {p.fix.approver}</p>}
        {p.alternatives.length > 0 && (
          <p className="mt-2 text-xs text-ink-soft">Other options: {p.alternatives.join(' ')}</p>
        )}
        <div className="mt-3"><HandoffList p={p} /></div>
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
          <FixAction p={p} size="sm" quiet />
          {p.fix.kind === 'handoff' && !p.status && <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>Plan handoff</Button>}
        </div>
      </div>
      {open && <div className="bg-canvas/70 px-4 pb-4 pt-1 sm:pl-[3.25rem]"><ProblemDetail p={p} /></div>}
    </li>
  )
}
