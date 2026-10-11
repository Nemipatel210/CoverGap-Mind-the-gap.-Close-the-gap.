import { useEffect, useState, type FormEvent } from 'react'
import { CalendarCheck, CheckCircle2, Clock, Hospital, LogOut, Stethoscope, XCircle } from 'lucide-react'
import { api, type Any, t } from '../api'
import { useAuth } from '../App'
import { Button, statusLabel, statusTone, Badge, useAction, usePoll } from '../ui'
import { Countdown } from './Offers'

/** Off-duty doctor's phone view at /m: sign in (prefilled for the demo), then see an offer and accept or decline. */
export default function PhysicianApp() {
  const { user } = useAuth()
  if (user?.role === 'doctor' && user.physician_id) return <Inbox pid={user.physician_id} name={user.name} />
  return <DoctorLogin staffSignedIn={!!user} />
}

function DoctorLogin({ staffSignedIn }: { staffSignedIn: boolean }) {
  const { signIn, signOut } = useAuth()
  const [accounts, setAccounts] = useState<Any>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.get('/api/auth/accounts').then((a: Any) => {
      setAccounts(a)
      setUsername((u) => u || a.default_doctor || '')
      setPassword((p) => p || a.password)
    }).catch((e) => setErr((e as Error).message))
  }, [])
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      if (staffSignedIn) await signOut()
      await signIn(username, password)
    } catch (ex) {
      setErr((ex as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const who = accounts?.doctors?.find((d: Any) => d.username === username)
  return (
    <div className="flex min-h-full flex-col bg-navy">
      <div className="px-6 pb-8 pt-10 text-white">
        <Stethoscope className="h-8 w-8 text-teal-100" />
        <p className="mt-4 text-2xl font-semibold">Sevaro shift offers</p>
        <p className="mt-1 text-sm text-white/70">Sign in to see extra-shift requests and reply in two taps.</p>
      </div>
      <form onSubmit={submit} className="mx-auto w-full max-w-md flex-1 rounded-t-3xl bg-canvas px-6 pb-10 pt-7">
        {who && <p className="text-sm text-ink-soft">Signing in as <span className="font-semibold text-navy">{who.name}</span></p>}
        <label className="mt-4 block text-sm font-medium" htmlFor="du">Username</label>
        <input id="du" value={username} onChange={(e) => setUsername(e.target.value)} autoCapitalize="none" autoComplete="username"
          className="mt-1 w-full rounded-xl border border-line bg-white px-4 py-3.5 text-base" />
        <label className="mt-3 block text-sm font-medium" htmlFor="dp">Password</label>
        <input id="dp" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
          className="mt-1 w-full rounded-xl border border-line bg-white px-4 py-3.5 text-base" />
        {err && <p className="mt-3 text-sm text-bad" role="alert">{err}</p>}
        <Button type="submit" size="lg" busy={busy} disabled={!username || !password} className="mt-6 w-full">Sign in</Button>
        {accounts?.doctors?.length > 1 && (
          <details className="mt-6 text-sm">
            <summary className="cursor-pointer text-teal-600">Demo: sign in as a different doctor</summary>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {accounts.doctors.map((d: Any) => (
                <button type="button" key={d.username} onClick={() => setUsername(d.username)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm ${d.username === username ? 'border-teal bg-teal-50 text-navy' : 'border-line bg-white'}`}>{d.name}</button>
              ))}
            </div>
          </details>
        )}
        <p className="mt-8 text-center text-xs text-ink-faint">Demo sign-in · synthetic data · offers never include patient information</p>
      </form>
    </div>
  )
}

function Phone({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full bg-canvas">
      <div className="mx-auto min-h-full max-w-md px-4 pb-10 pt-6">{children}</div>
    </div>
  )
}

function Inbox({ pid, name }: { pid: string; name?: string }) {
  const { signOut } = useAuth()
  const { data } = usePoll<Any>('/api/offers', 3000)
  const { run, busy } = useAction()
  const [done, setDone] = useState<Any>(null)
  const offers: Any[] = data?.offers ?? []
  const open = offers.filter((o) => o.status === 'sent')
  const upcoming = offers.filter((o) => o.status === 'accepted')
  const past = offers.filter((o) => !['sent', 'accepted', 'proposed', 'rejected'].includes(o.status))

  const respond = async (o: Any, action: 'accept' | 'decline') => {
    const r = await run(o.id + action, () => api.post(`/api/offers/${o.id}/respond`, { action }))
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
        <div className="flex-1">
          <p className="text-xs text-ink-soft">Sevaro shift offers</p>
          <h1 className="text-lg font-semibold text-navy">{name ?? pid}</h1>
        </div>
        <button onClick={() => signOut()} className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-ink-soft hover:bg-white"><LogOut className="h-4 w-4" />Sign out</button>
      </div>
      {!data && <p className="py-8 text-center text-sm text-ink-soft">Loading your offers…</p>}
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
