import { useEffect, useState } from 'react'
import { Smartphone, Timer } from 'lucide-react'
import { api, type Any, t, wall } from '../api'
import { useRole } from '../App'
import { Badge, Button, Empty, ErrorNote, Loading, PageHeader, Panel, Select, statusLabel, statusTone, useAction, usePoll } from '../ui'

export function Countdown({ until }: { until: string }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i) }, [])
  const s = Math.max(0, Math.round((new Date(until).getTime() - now) / 1000))
  return <span className={`num inline-flex items-center gap-1 font-medium ${s < 120 ? 'text-bad' : 'text-warn'}`}><Timer className="h-3.5 w-3.5" />{Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}</span>
}

export default function Offers() {
  const { actor } = useRole()
  const { data, error } = usePoll<Any>('/api/offers', 3000)
  const { run, busy } = useAction()
  const [status, setStatus] = useState('all')
  if (error && !data) return <ErrorNote text={error} />
  if (!data) return <Loading />
  const offers = data.offers.filter((o: Any) => status === 'all' || o.status === status)

  return (
    <div>
      <PageHeader title="Offers & escalations" lede="Every split-shift offer through its lifecycle: proposed, approved and sent, then accepted, declined, timed out or withdrawn once the gap was filled.">
        <Select label="Status" value={status} onChange={setStatus}>
          {['all', 'proposed', 'sent', 'accepted', 'declined', 'timed_out', 'rejected', 'not_needed', 'withdrawn'].map((s) => <option key={s} value={s}>{s === 'all' ? 'All statuses' : statusLabel(s)}</option>)}
        </Select>
      </PageHeader>
      <Panel pad={false} title={`Offers (${offers.length})`}>
        {offers.length === 0 && <div className="p-4"><Empty>No offers yet. Open a coverage incident from the command center to propose one.</Empty></div>}
        <ul className="divide-y divide-line">
          {offers.map((o: Any) => (
            <li key={o.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="num font-semibold text-navy">{o.id}</span>
                <span className="font-medium">{o.physician_name}</span>
                <span className="text-sm text-ink-soft">{o.hospital_names.join(', ')} · {t(o.start)}–{t(o.end)} · {o.policy.label}</span>
                <span className="ml-auto flex items-center gap-2">
                  {o.status === 'sent' && o.expires_wall && <Countdown until={o.expires_wall} />}
                  <Badge tone={statusTone(o.status)}>{statusLabel(o.status)}</Badge>
                </span>
              </div>
              <ol className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
                {o.history.map((h: Any, i: number) => (
                  <li key={i}><span className="font-medium text-ink">{statusLabel(h.status)}</span> by {h.by} at <span className="num">{wall(h.ts)}</span>{h.note ? ` — ${h.note}` : ''}</li>
                ))}
              </ol>
              {o.status === 'sent' && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <a className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-teal-600 hover:bg-teal-50" href={`/m/${o.physician_id}`} target="_blank" rel="noreferrer"><Smartphone className="h-3.5 w-3.5" />Open {o.physician_name}'s phone view</a>
                  <Button size="sm" variant="secondary" busy={busy === o.id} onClick={() => run(o.id, () => api.post(`/api/offers/${o.id}/expire`, { actor: `${actor} (demo)` }), 'Offer timed out; next eligible physician proposed if any')}>Simulate 10-minute timeout</Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </Panel>
      <Panel className="mt-5" pad={false} title={`Escalations (${data.escalations.length})`}>
        {data.escalations.length === 0 ? <p className="p-4 text-sm text-ink-soft">No escalations.</p> : (
          <ul className="divide-y divide-line">
            {data.escalations.map((e: Any) => (
              <li key={e.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm">
                <span className="num font-medium">{e.id}</span><span>{e.title}</span>
                <span className="text-xs text-ink-soft">raised by {e.created_by}</span>
                <Badge tone={statusTone(e.status)} className="ml-auto">{statusLabel(e.status)}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}
