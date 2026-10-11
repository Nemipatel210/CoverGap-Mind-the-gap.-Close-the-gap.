import { useState } from 'react'
import { ListChecks, ShieldAlert, UserPlus } from 'lucide-react'
import { api, type Any, t } from '../api'
import { useRole } from '../App'
import { Badge, Button, Empty, ErrorNote, Loading, statusLabel, statusTone, useAction, usePoll } from '../ui'
import { FixAction, ProblemDetail, Where, sevDot } from '../components/Problem'

/** Clinical lead: what puts stroke care at risk, and the decisions waiting on you. One step each. */
export default function Approvals() {
  const { actor, role } = useRole()
  const offers = usePoll<Any>('/api/offers', 3000)
  const probs = usePoll<Any>('/api/problems', 4000)
  const plans = usePoll<Any>('/api/plans', 3000)
  const { run, busy } = useAction()
  const [note, setNote] = useState<Record<string, string>>({})
  const [open, setOpen] = useState<string | null>(null)
  if (offers.error && !offers.data) return <ErrorNote text={offers.error} />
  if (!offers.data || !probs.data) return <Loading />
  const pending = offers.data.offers.filter((o: Any) => o.status === 'proposed')
  const planList: Any[] = plans.data?.plans ?? []
  const pendingPlans = planList.filter((x) => x.status === 'pending')
  const esc = offers.data.escalations.filter((e: Any) => e.status === 'pending')
  const recent = [...planList.filter((x: Any) => x.status !== 'pending').map((x: Any) => ({ id: x.id, title: `Plan ${x.chosen.key}: ${x.chosen.label}`, status: x.status === 'done' ? 'authorized' : x.status })), ...offers.data.offers.filter((o: Any) => o.status !== 'proposed'), ...offers.data.escalations.filter((e: Any) => e.status !== 'pending')].slice(0, 8)
  const risk = probs.data.problems.filter((p: Any) => (p.stroke || p.kind === 'hospital') && p.severity === 'critical')
  const isLead = role === 'clinical_lead'
  const decide = (key: string, path: string, body: Any, msg: string) => run(key, () => api.post(path, { ...body, actor, note: note[key.replace(/[ar]$/, '')] ?? note[key] }), msg)

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-2xl font-semibold tracking-tight text-navy">Waiting for your decision</h1>
      <p className="mt-1 text-sm text-ink-soft">Approve or reject in one step. Nothing reaches an off-duty doctor without your approval.</p>
      {!isLead && <p className="mt-3 rounded-lg border border-warn/30 bg-warn-50 p-3 text-sm text-warn">You're signed in as the coordinator. Sign in as the clinical lead to decide.</p>}

      <div className="mt-5 space-y-3">
        {pending.length === 0 && esc.length === 0 && pendingPlans.length === 0 && <Empty>Nothing waiting for you right now.</Empty>}
        {pendingPlans.map((x: Any) => (
          <article key={x.id} className={`rounded-2xl border-2 bg-white p-5 ${x.severity === 'critical' ? 'border-bad/40' : 'border-navy/40'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <ListChecks className="h-4 w-4 text-teal-600" />
              <h2 className="font-semibold text-navy">{x.what}</h2>
              {x.stroke && <Badge tone="critical">Stroke</Badge>}
            </div>
            <p className="mt-0.5"><Where w={x.where} /></p>
            <ul className="mt-2 list-disc space-y-0.5 pl-4 text-sm text-ink-soft">{x.matters.slice(0, 3).map((m: string, i: number) => <li key={i}>{m}</li>)}</ul>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border-2 border-teal bg-teal-50/70 p-3">
                <p className="text-xs font-medium text-teal-700">Coordinator chose Plan {x.chosen.key}{x.chosen.recommended ? ' (recommended)' : ''}</p>
                <p className="mt-1 font-semibold text-navy">{x.chosen.label}</p>
                <p className="mt-1 text-sm">{x.chosen.why}</p>
                <p className="mt-1 text-xs text-ink-soft"><span className="font-medium text-ink">If approved: </span>{x.chosen.effect}</p>
              </div>
              {x.other && (
                <div className="rounded-xl border border-line p-3 text-ink-soft">
                  <p className="text-xs font-medium">Other option: Plan {x.other.key}</p>
                  <p className="mt-1 font-medium text-ink">{x.other.label}</p>
                  <p className="mt-1 text-sm">{x.other.why}</p>
                </div>
              )}
            </div>
            <p className="mt-2 text-xs text-ink-soft">Sent by {x.proposed_by}. Approving runs the plan straight away.</p>
            {isLead && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <input value={note[x.id] ?? ''} onChange={(e) => setNote({ ...note, [x.id]: e.target.value })} placeholder="Note (optional)" aria-label="Note"
                  className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm" />
                <Button variant="danger" busy={busy === x.id + 'r'} onClick={() => decide(x.id + 'r', `/api/plans/${x.id}/reject`, {}, `Plan ${x.chosen.key} rejected`)}>Reject</Button>
                <Button variant="success" busy={busy === x.id + 'a'} onClick={() => decide(x.id + 'a', `/api/plans/${x.id}/approve`, {}, `Plan ${x.chosen.key} approved`)}>Approve Plan {x.chosen.key}</Button>
              </div>
            )}
          </article>
        ))}
        {pending.map((o: Any) => (
          <article key={o.id} className="rounded-2xl border-2 border-navy/70 bg-white p-5">
            <div className="flex flex-wrap items-center gap-2">
              <UserPlus className="h-4 w-4 text-teal-600" />
              <h2 className="font-semibold text-navy">Extra shift for {o.physician_name}</h2>
              {o.auto_proposed && <Badge tone="info">Next eligible doctor</Badge>}
            </div>
            <p className="num mt-2 text-sm">{o.hospital_names.join(', ')} · {t(o.start)}–{t(o.end)} ({o.hours}h) · online by {t(o.effective_start)}</p>
            <p className="mt-1 text-sm text-ink-soft">{o.why} {o.considered.filter((c: Any) => c.eligible).length} of {o.considered.length} off-duty doctors pass every rule. Routing is limited to these hospitals so the new doctor isn't swamped.</p>
            <button className="mt-1 text-xs font-medium text-teal-600" onClick={() => setOpen(open === o.id ? null : o.id)}>{open === o.id ? 'Hide' : 'Show'} who was excluded and why</button>
            {open === o.id && (
              <ul className="mt-2 space-y-0.5 text-xs">
                {o.considered.map((c: Any) => <li key={c.physician_id}><span className="font-medium">{c.name}</span>: {c.eligible ? <span className="text-ok">eligible</span> : <span className="text-ink-soft">{c.failed_rules.join('; ')}</span>}</li>)}
              </ul>
            )}
            {isLead && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <input value={note[o.id] ?? ''} onChange={(e) => setNote({ ...note, [o.id]: e.target.value })} placeholder="Note (optional)" aria-label="Note"
                  className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm" />
                <Button variant="danger" busy={busy === o.id + 'r'} onClick={() => decide(o.id + 'r', `/api/offers/${o.id}/reject`, {}, 'Offer rejected')}>Reject</Button>
                <Button variant="success" busy={busy === o.id + 'a'} onClick={() => decide(o.id + 'a', `/api/offers/${o.id}/approve`, {}, `Approved and sent to ${o.physician_name}`)}>Approve and send</Button>
              </div>
            )}
          </article>
        ))}
        {esc.map((e: Any) => (
          <article key={e.id} className="rounded-2xl border-2 border-bad/40 bg-white p-5">
            <div className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-bad" /><h2 className="font-semibold text-navy">Escalation: {e.title}</h2></div>
            <p className="mt-1 text-sm text-ink-soft">{e.detail}</p>
            {isLead && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <input value={note[e.id] ?? ''} onChange={(ev) => setNote({ ...note, [e.id]: ev.target.value })} placeholder="What you'll do (optional)" aria-label="Note"
                  className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm" />
                <Button variant="danger" busy={busy === e.id + 'r'} onClick={() => decide(e.id + 'r', `/api/escalations/${e.id}/decide`, { decision: 'reject' }, 'Escalation rejected')}>Reject</Button>
                <Button variant="success" busy={busy === e.id + 'a'} onClick={() => decide(e.id + 'a', `/api/escalations/${e.id}/decide`, { decision: 'authorize' }, 'Escalation authorized')}>Authorize</Button>
              </div>
            )}
          </article>
        ))}
      </div>

      <h2 className="mb-2 mt-8 text-sm font-semibold text-navy">Stroke care at risk ({risk.length})</h2>
      {risk.length === 0 ? <Empty>No critical stroke or coverage risks.</Empty> : (
        <ul className="overflow-hidden rounded-xl border border-line bg-white">
          {risk.map((p: Any) => (
            <li key={p.id} className="border-t border-line first:border-t-0">
              <div className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-3">
                <button onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id} className="flex min-w-0 items-start gap-3 text-left sm:flex-1">
                  <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${sevDot(p.severity)}`} />
                  <span className="min-w-0"><span className="block text-sm font-medium">{p.what}</span><Where w={p.where} /></span>
                </button>
                <FixAction p={p} />
              </div>
              {open === p.id && <div className="bg-canvas/70 px-4 pb-4 pl-10 pt-1"><ProblemDetail p={p} /></div>}
            </li>
          ))}
        </ul>
      )}

      {recent.length > 0 && (
        <>
          <h2 className="mb-2 mt-8 text-sm font-semibold text-navy">Recent decisions</h2>
          <ul className="divide-y divide-line rounded-xl border border-line bg-white">
            {recent.map((x: Any) => (
              <li key={x.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
                <span>{x.physician_name ? `Extra shift: ${x.physician_name}` : x.title}</span>
                <Badge tone={statusTone(x.status)} className="ml-auto">{statusLabel(x.status)}</Badge>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
