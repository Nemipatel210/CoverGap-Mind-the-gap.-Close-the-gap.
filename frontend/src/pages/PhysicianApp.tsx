import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CalendarCheck, CheckCircle2, ChevronLeft, Clock, Hospital, XCircle } from 'lucide-react'
import { api, type Any, t } from '../api'
import { Button, Loading, statusLabel, statusTone, Badge, useAction, usePoll } from '../ui'
import { Countdown } from './Offers'

/** Off-shift physician's phone view: see an offer, accept or decline. Nothing else. */
export default function PhysicianApp() {
  const { physicianId } = useParams()
  const meta = usePoll<Any>('/api/meta', 15000)
  if (!physicianId) {
    return (
      <Phone>
        <h1 className="text-xl font-semibold text-navy">Who's signing in?</h1>
        <p className="mt-1 text-sm text-ink-soft">Demo sign-in. Pick an off-shift physician to see their offers.</p>
        {!meta.data ? <Loading /> : (
          <ul className="mt-4 space-y-2">
            {meta.data.off_shift.map((p: Any) => (
              <li key={p.physician_id}>
                <Link to={`/m/${p.physician_id}`} className="flex items-center justify-between rounded-xl border border-line bg-white px-4 py-3.5 text-base font-medium hover:border-teal">
                  {p.name}<span className="text-xs text-ink-faint">{p.physician_id}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <Link to="/" className="mt-6 block text-center text-sm text-teal-600">Back to the command center</Link>
      </Phone>
    )
  }
  return <Inbox pid={physicianId} name={meta.data?.off_shift.find((p: Any) => p.physician_id === physicianId)?.name ?? meta.data?.on_shift.find((p: Any) => p.physician_id === physicianId)?.name} />
}

function Phone({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full bg-canvas">
      <div className="mx-auto min-h-full max-w-md px-4 pb-10 pt-6">{children}</div>
    </div>
  )
}

function Inbox({ pid, name }: { pid: string; name?: string }) {
  const nav = useNavigate()
  const { data } = usePoll<Any>(`/api/offers?physician_id=${pid}`, 3000)
  const { run, busy } = useAction()
  const [done, setDone] = useState<Any>(null)
  const offers: Any[] = data?.offers ?? []
  const open = offers.filter((o) => o.status === 'sent')
  const upcoming = offers.filter((o) => o.status === 'accepted')
  const past = offers.filter((o) => !['sent', 'accepted', 'proposed', 'rejected'].includes(o.status))

  const respond = async (o: Any, action: 'accept' | 'decline') => {
    const r = await run(o.id + action, () => api.post(`/api/offers/${o.id}/respond`, { physician_id: pid, action }))
    if (r) setDone(r)
  }

  if (done) {
    const ok = done.status === 'accepted'
    const filled = done.status === 'not_needed'
    return (
      <Phone>
        <div className="flex min-h-[70vh] flex-col items-center justify-center text-center">
          {ok ? <CheckCircle2 className="h-16 w-16 text-ok" /> : filled ? <CalendarCheck className="h-16 w-16 text-navy" /> : <XCircle className="h-16 w-16 text-ink-faint" />}
          <h1 className="mt-4 text-2xl font-semibold text-navy">{ok ? "You're confirmed" : filled ? 'Already covered' : 'Offer declined'}</h1>
          <p className="mt-2 text-ink-soft">
            {ok ? `${done.hospital_names.join(', ')} · ${t(done.start)}–${t(done.end)} ET. Please be online by about ${t(done.effective_start)}.`
              : filled ? 'Another physician accepted first, so you are not needed. Thank you for responding.'
                : 'Thanks for letting us know. The team will ask someone else.'}
          </p>
          <Button className="mt-8 w-full" size="lg" variant="secondary" onClick={() => setDone(null)}>Back to my offers</Button>
        </div>
      </Phone>
    )
  }

  return (
    <Phone>
      <div className="mb-5 flex items-center gap-2">
        <button aria-label="Switch physician" onClick={() => nav('/m')} className="rounded-lg p-1 hover:bg-white"><ChevronLeft className="h-5 w-5 text-navy" /></button>
        <div>
          <p className="text-xs text-ink-soft">Sevaro shift offers</p>
          <h1 className="text-lg font-semibold text-navy">{name ?? pid}</h1>
        </div>
      </div>
      {!data && <Loading />}
      {data && open.length === 0 && (
        <div className="rounded-2xl border border-line bg-white p-6 text-center">
          <Clock className="mx-auto h-8 w-8 text-ink-faint" />
          <p className="mt-2 font-medium">No open offers</p>
          <p className="text-sm text-ink-soft">New offers appear here as soon as the clinical lead approves them.</p>
        </div>
      )}
      {open.map((o) => (
        <article key={o.id} className="arrive mb-4 overflow-hidden rounded-2xl border border-teal/40 bg-white">
          <div className="bg-navy px-5 py-4 text-white">
            <p className="text-sm text-white/70">Split-shift request</p>
            <p className="num mt-0.5 text-3xl font-semibold">{t(o.start)}–{t(o.end)}</p>
            <p className="text-sm text-white/80">{new Date(o.start).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'America/New_York' })} · {o.hours} hours · ET</p>
          </div>
          <div className="space-y-3 px-5 py-4">
            <div className="flex gap-2"><Hospital className="mt-0.5 h-5 w-5 shrink-0 text-teal-600" /><div><p className="text-xs text-ink-soft">Hospitals</p><p className="font-medium">{o.hospital_names.join(', ')}</p></div></div>
            <div className="flex gap-2"><Clock className="mt-0.5 h-5 w-5 shrink-0 text-teal-600" /><div><p className="text-xs text-ink-soft">Start</p><p className="font-medium">{t(o.start)} ET — about {o.est_minutes_to_online} min to come online</p></div></div>
            <div><p className="text-xs text-ink-soft">Why you were asked</p><p className="text-sm">{o.why} You're credentialed there and within rest and hour limits.</p></div>
            <p className="text-sm">Reply within <Countdown until={o.expires_wall} /></p>
          </div>
          <div className="grid grid-cols-2 gap-3 px-5 pb-5">
            <Button size="lg" variant="secondary" busy={busy === o.id + 'decline'} onClick={() => respond(o, 'decline')}>Decline</Button>
            <Button size="lg" variant="success" busy={busy === o.id + 'accept'} onClick={() => respond(o, 'accept')}>Accept</Button>
          </div>
        </article>
      ))}
      {upcoming.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-navy">Upcoming shifts</h2>
          {upcoming.map((o) => (
            <div key={o.id} className="mb-2 flex items-center gap-3 rounded-xl border border-ok/30 bg-ok-50 px-4 py-3">
              <CalendarCheck className="h-5 w-5 text-ok" />
              <div className="flex-1"><p className="num font-medium">{t(o.start)}–{t(o.end)} ET</p><p className="text-sm text-ink-soft">{o.hospital_names.join(', ')}</p></div>
            </div>
          ))}
        </section>
      )}
      {past.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-navy">Your responses</h2>
          <ul className="divide-y divide-line rounded-xl border border-line bg-white">
            {past.map((o) => (
              <li key={o.id} className="flex items-center justify-between px-4 py-3 text-sm">
                <span className="num">{t(o.start)}–{t(o.end)} · {o.hospital_names.join(', ')}</span>
                <Badge tone={statusTone(o.status)}>{statusLabel(o.status)}</Badge>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="mt-8 text-center text-xs text-ink-faint">Offers never include patient information. Synthetic demo data.</p>
    </Phone>
  )
}
