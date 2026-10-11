import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Check, ChevronDown, ChevronRight, X } from 'lucide-react'
import { api, type Any, t } from '../api'
import { useRole } from '../App'
import { Badge, Button, ErrorNote, Loading, statusLabel, statusTone, useAction, usePoll } from '../ui'

/** Split-shift decision: who to call in, why them, why not the others, and how they won't get swamped. */
export default function Decision() {
  const { incidentId = '' } = useParams()
  const [sp] = useSearchParams()
  const problemId = sp.get('for')
  const { role, actor } = useRole()
  const { data, error } = usePoll<Any>(`/api/incidents/${encodeURIComponent(incidentId)}/plan`, 6000)
  const offers = usePoll<Any>('/api/offers', 4000)
  const { run, busy } = useAction()
  const [openRow, setOpenRow] = useState<string | null>(null)
  const [showSim, setShowSim] = useState(false)

  const back = <Link to="/" className="mb-4 inline-flex items-center gap-1 text-sm text-teal-600"><ArrowLeft className="h-4 w-4" />What to do now</Link>
  if (error && !data) return <div className="mx-auto max-w-3xl">{back}<ErrorNote text={error} /></div>
  if (!data) return <Loading label="Checking every off-duty doctor" />

  const inc = data.incident
  const top = data.top
  const short = inc.hospitals.filter((h: string) => inc.remaining[h] > 0)
  const name = (h: string) => inc.hospital_names[inc.hospitals.indexOf(h)]
  const mine = (offers.data?.offers ?? []).filter((o: Any) => o.incident_id === inc.id)
  const live = mine.find((o: Any) => ['proposed', 'sent', 'accepted'].includes(o.status))
  const rec = data.simulation.find((s: Any) => s.policy === data.recommended_policy)
  const naive = data.simulation.find((s: Any) => s.policy === 'naive')
  const notCovered = top ? short.filter((h: string) => !top.scoped_hospitals.includes(h) || inc.remaining[h] > 1) : short

  return (
    <div className="mx-auto max-w-3xl">
      {back}
      <h1 className="text-2xl font-semibold tracking-tight text-navy">Call in an off-duty doctor</h1>
      <p className="mt-1 text-sm text-ink-soft">
        {inc.title.toLowerCase().includes('now') ? 'Short right now' : inc.title} at {short.map(name).join(', ') || inc.hospital_names.join(', ')}.
      </p>

      {top ? (
        <section className="mt-5 rounded-2xl border-2 border-navy/80 bg-white p-5">
          <p className="text-xs font-medium text-ink-soft">Recommended</p>
          <h2 className="mt-0.5 text-xl font-semibold text-ink">{top.name}</h2>
          <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="text-xs text-ink-soft">Hours</dt><dd className="num font-medium">{t(data.offer.start)}–{t(data.offer.end)} ({data.offer.hours}h)</dd></div>
            <div><dt className="text-xs text-ink-soft">Online by</dt><dd className="num font-medium">{t(top.online_at)} <span className="font-normal text-ink-soft">({top.est_minutes_to_online} min to log in)</span></dd></div>
            <div><dt className="text-xs text-ink-soft">Covers</dt><dd className="font-medium">{top.scoped_hospital_names.join(', ')}</dd></div>
          </dl>
          <p className="mt-4 text-sm"><span className="font-medium">Why this doctor: </span>
            {data.eligible_count === 1 ? `the only one of ${data.candidates.length} off-duty doctors who passes every rule.` : `passes every rule and is first of ${data.eligible_count} eligible doctors.`}
          </p>
          <p className="mt-1 text-sm"><span className="font-medium">If approved: </span>
            adds an approved doctor at {top.scoped_hospital_names.join(' and ')} from {t(top.online_at)}.
            {notCovered.length > 0 && <> Still short at {notCovered.map(name).join(', ')}, so that goes to the clinical lead.</>}
          </p>
          <p className="mt-1 text-sm"><span className="font-medium">If rejected or declined: </span>
            {data.eligible_count > 1 ? 'the next eligible doctor is proposed.' : 'nobody else can be asked, so it is escalated to the clinical lead.'}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            {live ? (
              <><Badge tone={statusTone(live.status)}>{live.physician_name}: {statusLabel(live.status)}</Badge><Link to="/offers" className="text-sm font-medium text-teal-600">Track offer</Link></>
            ) : role === 'coordinator' ? (
              <Button size="lg" busy={busy === 'propose'}
                onClick={() => run('propose', () => api.post('/api/offers', { incident_id: inc.id, physician_id: top.physician_id, policy: data.recommended_policy, actor }),
                  (o) => `Sent to the clinical lead for approval (${o.id})`)}>
                Send to clinical lead for approval
              </Button>
            ) : <Link to="/approvals" className="text-sm font-medium text-teal-600">Go to approvals</Link>}
            <span className="text-xs text-ink-soft">Nothing reaches the doctor until the clinical lead approves.</span>
          </div>
        </section>
      ) : (
        <section className="mt-5 rounded-2xl border-2 border-bad/50 bg-white p-5">
          <h2 className="text-xl font-semibold text-ink">Nobody can be asked</h2>
          <p className="mt-1 text-sm">None of the {data.candidates.length} off-duty doctors passes every rule. The rules aren't bent; this goes to the clinical lead.</p>
          {role === 'coordinator' && problemId && (
            <Button className="mt-4" size="lg" busy={busy === 'esc'} onClick={() => run('esc', () => api.post(`/api/problems/${encodeURIComponent(problemId)}/escalate`, { actor }), 'Escalated to the clinical lead')}>
              Escalate to the clinical lead</Button>
          )}
        </section>
      )}

      <section className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-navy">Everyone considered ({data.candidates.length})</h2>
        <ul className="overflow-hidden rounded-xl border border-line bg-white">
          {data.candidates.map((c: Any) => (
            <li key={c.physician_id} className="border-t border-line first:border-t-0">
              <button onClick={() => setOpenRow(openRow === c.physician_id ? null : c.physician_id)} aria-expanded={openRow === c.physician_id}
                className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-canvas">
                {c.eligible ? <Check className="h-5 w-5 shrink-0 text-ok" aria-label="eligible" /> : <X className="h-5 w-5 shrink-0 text-bad" aria-label="not eligible" />}
                <span className="w-40 shrink-0 text-sm font-medium">{c.name}</span>
                <span className={`flex-1 text-sm ${c.eligible ? 'text-ok' : 'text-ink-soft'}`}>{c.reason}</span>
                {openRow === c.physician_id ? <ChevronDown className="h-4 w-4 text-ink-faint" /> : <ChevronRight className="h-4 w-4 text-ink-faint" />}
              </button>
              {openRow === c.physician_id && (
                <ul className="grid gap-1 bg-canvas/70 px-4 py-3 pl-12 text-sm sm:grid-cols-2">
                  {c.rules.map((r: Any) => (
                    <li key={r.rule} className="flex gap-2">
                      {r.pass ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" /> : <X className="mt-0.5 h-4 w-4 shrink-0 text-bad" />}
                      <span><span className={r.pass ? '' : 'font-medium text-bad'}>{r.rule}</span><span className="block text-xs text-ink-soft">{r.detail}</span></span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </section>

      {rec && naive && (
        <section className="mt-6 rounded-xl border border-line bg-white p-4">
          <h2 className="text-sm font-semibold text-navy">Keeping the new doctor from being swamped</h2>
          <p className="mt-1 text-sm text-ink-soft">Routing sends calls to whoever has the fewest consults. Joining at zero, they would get calls from every hospital they're approved at. We limit them to the short hospitals and start their count at {rec.seed}.</p>
          <table className="mt-3 w-full text-sm">
            <thead className="text-left text-xs text-ink-soft"><tr><th className="py-1 font-medium" /><th className="py-1 text-right font-medium">Calls to the new doctor</th><th className="py-1 text-right font-medium">From hospitals that weren't short</th></tr></thead>
            <tbody className="divide-y divide-line">
              <tr><td className="py-1.5">Normal routing</td><td className="num py-1.5 text-right">{naive.joiner_total}</td><td className="num py-1.5 text-right font-medium text-warn">{naive.joiner_other}</td></tr>
              <tr className="bg-teal-50/60"><td className="py-1.5 font-medium">Our plan: short hospitals only, count starts at {rec.seed}</td><td className="num py-1.5 text-right">{rec.joiner_total}</td><td className="num py-1.5 text-right font-medium text-ok">{rec.joiner_other}</td></tr>
            </tbody>
          </table>
          <button className="mt-2 text-xs font-medium text-teal-600" onClick={() => setShowSim(!showSim)}>{showSim ? 'Hide' : 'Show'} how this was worked out</button>
          {showSim && (
            <div className="mt-2 text-xs text-ink-soft">
              <p>We replayed the routing rules over the {data.offer.hours}h window using each hospital's normal volume ({rec.arrivals} expected calls network-wide, busy-level volume where a surge continues). Each consult keeps a doctor busy for a set time. All four options:</p>
              <ul className="mt-1 space-y-0.5">
                {data.simulation.map((s: Any) => <li key={s.policy}>{s.label}: {s.joiner_total} calls, {s.joiner_other} from other hospitals, {s.unrouted_gap} unanswered at short hospitals.</li>)}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
