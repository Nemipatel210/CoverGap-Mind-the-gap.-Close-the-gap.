import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ClipboardCheck, Gauge, Smartphone } from 'lucide-react'
import { api, type Any } from '../api'
import { useAuth } from '../App'
import { Button } from '../ui'

const ROLES = [
  { username: 'coordinator', icon: Gauge, title: 'Operations coordinator', blurb: 'Sees what needs attention and acts on it.' },
  { username: 'lead', icon: ClipboardCheck, title: 'Clinical lead on duty', blurb: 'Approves extra shifts and escalations.' },
]

/** Staff sign-in. Demo accounts are prefilled: pick a role and press Sign in. */
export default function Login() {
  const { user, signIn } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [username, setUsername] = useState('coordinator')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.get('/api/auth/accounts').then((a: Any) => setPassword((p) => p || a.password)).catch(() => setPassword('demo1234'))
  }, [])

  if (user) return <Navigate to={user.role === 'doctor' ? '/m' : user.role === 'clinical_lead' ? '/approvals' : '/'} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      const u = await signIn(username, password)
      const from = (loc.state as Any)?.from
      nav(u.role === 'doctor' ? '/m' : u.role === 'clinical_lead' ? '/approvals' : from && from !== '/login' ? from : '/', { replace: true })
    } catch (ex) {
      setErr((ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1fr_1.1fr]">
      <div className="hidden flex-col justify-between bg-navy p-10 text-white lg:flex">
        <div>
          <p className="text-xl font-semibold tracking-tight">Sevaro</p>
          <p className="text-sm text-white/60">Operations command center</p>
        </div>
        <div className="max-w-md">
          <p className="text-3xl font-semibold leading-tight">See the gap early. Decide who covers it. Get it approved.</p>
          <p className="mt-4 text-sm leading-relaxed text-white/70">For tele-neurology coverage across every hospital: what needs attention first, who can be called in, and a clinical-lead approval before any doctor is contacted.</p>
        </div>
        <p className="text-xs text-white/40">Prototype · synthetic data only · demo sign-in</p>
      </div>

      <div className="flex items-center justify-center bg-canvas p-5 sm:p-10">
        <form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-line bg-white p-6 sm:p-8">
          <p className="text-lg font-semibold text-navy lg:hidden">Sevaro</p>
          <h1 className="text-2xl font-semibold tracking-tight text-navy">Sign in</h1>
          <p className="mt-1 text-sm text-ink-soft">Demo accounts are filled in. Choose a role and sign in.</p>

          <fieldset className="mt-5 grid gap-2 sm:grid-cols-2">
            <legend className="sr-only">Role</legend>
            {ROLES.map((r) => (
              <label key={r.username} className={`flex cursor-pointer flex-col rounded-xl border p-3 ${username === r.username ? 'border-teal bg-teal-50 ring-1 ring-teal' : 'border-line hover:border-ink-faint'}`}>
                <input type="radio" name="role" className="sr-only" checked={username === r.username} onChange={() => setUsername(r.username)} />
                <r.icon className={`h-5 w-5 ${username === r.username ? 'text-teal-600' : 'text-ink-faint'}`} />
                <span className="mt-2 text-sm font-medium text-navy">{r.title}</span>
                <span className="mt-0.5 text-xs text-ink-soft">{r.blurb}</span>
              </label>
            ))}
          </fieldset>

          <label className="mt-5 block text-sm font-medium" htmlFor="u">Username</label>
          <input id="u" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
            className="mt-1 w-full rounded-lg border border-line px-3 py-2.5 text-sm" />
          <label className="mt-3 block text-sm font-medium" htmlFor="p">Password</label>
          <input id="p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
            className="mt-1 w-full rounded-lg border border-line px-3 py-2.5 text-sm" />
          {err && <p className="mt-3 text-sm text-bad" role="alert">{err}</p>}
          <Button type="submit" size="lg" busy={busy} className="mt-5 w-full">Sign in</Button>

          <div className="mt-6 flex gap-3 rounded-xl bg-canvas p-3 text-xs text-ink-soft">
            <Smartphone className="h-4 w-4 shrink-0 text-teal-600" />
            <p>Off-duty doctors sign in on their phone at <span className="font-medium text-navy">{window.location.host}/m</span></p>
          </div>
        </form>
      </div>
    </div>
  )
}
