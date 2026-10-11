import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Activity, Bell, ClipboardCheck, Database, Gauge, LayoutGrid, LogOut, Menu, Send, Settings as Cog, Users, X } from 'lucide-react'
import { api, tokenStore, wall, type Any } from './api'
import { Badge, Loading, ToastHost, announceChange, usePoll, useToast } from './ui'
import { TimeControl } from './components/TimeControl'
import CommandCenter from './pages/CommandCenter'
import Details from './pages/Details'
import Coverage from './pages/Coverage'
import Decision from './pages/Decision'
import Approvals from './pages/Approvals'
import Offers from './pages/Offers'
import ActivityLog from './pages/ActivityLog'
import DataManagement from './pages/DataManagement'
import Settings from './pages/Settings'
import PhysicianApp from './pages/PhysicianApp'
import Login from './pages/Login'

/* ------------------------------------------------------------------ session --- */
export type Role = 'coordinator' | 'clinical_lead'
export type User = { role: Role | 'doctor' | 'admin'; name: string; title: string; username: string; physician_id?: string }
type AuthCtx = { user: User | null; ready: boolean; signIn: (u: string, p: string) => Promise<User>; signOut: () => Promise<void> }
const Auth = createContext<AuthCtx>({ user: null, ready: false, signIn: async () => { throw new Error('no auth') }, signOut: async () => {} })
export const useAuth = () => useContext(Auth)

/** Kept for the pages: the signed-in role and the name that goes in the record of actions. */
export const useRole = () => {
  const { user } = useAuth()
  return { role: (user?.role === 'clinical_lead' ? 'clinical_lead' : 'coordinator') as Role, actor: user?.name ?? '' }
}

function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    if (!tokenStore.get()) { setReady(true); return }
    api.get('/api/auth/me').then((u) => setUser(u?.role ? u : null)).catch(() => tokenStore.set(null)).finally(() => setReady(true))
  }, [])
  useEffect(() => {
    const out = () => { tokenStore.set(null); setUser(null) }
    window.addEventListener('sevaro:signed-out', out)
    return () => window.removeEventListener('sevaro:signed-out', out)
  }, [])
  const signIn = useCallback(async (username: string, password: string) => {
    const r = await api.post('/api/auth/login', { username, password })
    tokenStore.set(r.token)
    const { token: _t, ...u } = r
    setUser(u)
    return u as User
  }, [])
  const signOut = useCallback(async () => {
    try { await api.post('/api/auth/logout') } catch { /* already signed out */ }
    tokenStore.set(null)
    setUser(null)
  }, [])
  return <Auth.Provider value={{ user, ready, signIn, signOut }}>{children}</Auth.Provider>
}

/* ---------------------------------------------------------------- staff app --- */
const NAV: Record<Role, { to: string; label: string; icon: typeof Gauge }[]> = {
  coordinator: [
    { to: '/', label: 'What to do now', icon: Gauge },
    { to: '/coverage', label: 'Coverage ahead', icon: LayoutGrid },
    { to: '/offers', label: 'Offers', icon: Send },
    { to: '/data', label: 'Add new events', icon: Database },
    { to: '/details', label: 'Doctors & consults', icon: Users },
    { to: '/activity', label: 'Record of actions', icon: Activity },
  ],
  clinical_lead: [
    { to: '/approvals', label: 'Your decisions', icon: ClipboardCheck },
    { to: '/coverage', label: 'Coverage ahead', icon: LayoutGrid },
    { to: '/activity', label: 'Record of actions', icon: Activity },
  ],
}

function Shell() {
  const { user, ready, signOut } = useAuth()
  const { role } = useRole()
  const [menu, setMenu] = useState(false)
  const [bell, setBell] = useState(false)
  const nav = useNavigate()
  const loc = useLocation()
  const signedIn = !!user && user.role !== 'doctor'
  const meta = usePoll<Any>(signedIn ? '/api/meta' : null, 5000)
  const notes = usePoll<Any>(signedIn ? `/api/notifications?audience=${role}` : null, 4000)
  const approvals = usePoll<Any>(signedIn ? '/api/offers?status=proposed' : null, 4000)
  const planQueue = usePoll<Any>(signedIn ? '/api/plans?status=pending' : null, 4000)
  useEffect(() => setMenu(false), [loc.pathname])
  // Pop up new alerts as they are generated (e.g. while the demo clock moves forward).
  const toast = useToast()
  const seen = useRef<Set<string> | null>(null)
  const mountedAt = useRef(Date.now())
  useEffect(() => {
    const list: Any[] = notes.data?.notifications ?? []
    if (!notes.data) return
    if (seen.current === null) { seen.current = new Set(list.map((n) => n.id)); return }
    const fresh = list.filter((n) => !seen.current!.has(n.id))
    fresh.forEach((n) => seen.current!.add(n.id))
    fresh.filter((n) => !n.read && ['alert', 'approval', 'escalation', 'offer', 'call'].includes(n.kind) && new Date(n.created).getTime() >= mountedAt.current - 2000).slice(0, 3)
      .forEach((n) => toast(n.severity === 'critical' ? 'alert' : 'info', `${n.title}${n.body ? ' · ' + n.body : ''}`))
  }, [notes.data, toast])

  if (!ready) return <Loading />
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (user.role === 'doctor') return <Navigate to="/m" replace />

  const pending = (approvals.data?.offers?.length ?? 0) + (approvals.data?.escalations?.filter((e: Any) => e.status === 'pending').length ?? 0) + (planQueue.data?.plans?.length ?? 0)
  const unread = notes.data?.unread ?? 0
  const home = role === 'clinical_lead' ? '/approvals' : '/'

  const side = (
    <nav className="flex h-full flex-col bg-navy text-white">
      <div className="px-5 pb-5 pt-6">
        <div className="text-lg font-semibold tracking-tight">Sevaro</div>
        <div className="text-[13px] text-white/60">Operations command center</div>
      </div>
      <div className="flex-1 space-y-0.5 px-3">
        {NAV[role].map((n) => (
          <NavLink key={n.to + n.label} to={n.to} end={n.to === '/'}
            className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-teal font-medium text-white' : 'text-white/75 hover:bg-white/10 hover:text-white'}`}>
            <n.icon className="h-4 w-4" />
            <span className="flex-1">{n.label}</span>
            {n.to === '/approvals' && pending > 0 && <span className="rounded-full bg-warn px-1.5 text-xs font-semibold">{pending}</span>}
          </NavLink>
        ))}
      </div>
      <div className="m-3 rounded-lg bg-white/5 p-3">
        <p className="text-sm font-medium">{user.name}</p>
        <p className="text-xs text-white/60">{user.title}</p>
        <button onClick={async () => { await signOut(); nav('/login') }} className="mt-2 inline-flex items-center gap-1.5 text-xs text-white/80 hover:text-white">
          <LogOut className="h-3.5 w-3.5" />Sign out
        </button>
      </div>
      <p className="mx-4 mb-4 text-xs text-white/40">Prototype · synthetic data only</p>
    </nav>
  )

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 lg:block">{side}</aside>
      {menu && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setMenu(false)}>
          <div className="absolute inset-y-0 left-0 w-64" onClick={(e) => e.stopPropagation()}>{side}</div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-white/95 px-4 py-2.5 backdrop-blur sm:px-6">
          <button className="lg:hidden" aria-label="Open menu" onClick={() => setMenu(true)}><Menu className="h-5 w-5 text-navy" /></button>
          <TimeControl clock={meta.data?.clock} label={meta.data?.as_of_label} canEdit={role === 'coordinator'} />
          <span className="hidden rounded-full bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-700 sm:inline">{user.title}</span>
          {role === 'coordinator' && <NavLink to="/settings" aria-label="Settings" className="rounded-lg p-2 hover:bg-canvas"><Cog className="h-5 w-5 text-navy" /></NavLink>}
          <button aria-label="Notifications" onClick={() => setBell(true)} className="relative rounded-lg p-2 hover:bg-canvas">
            <Bell className="h-5 w-5 text-navy" />
            {unread > 0 && <span className="num absolute -right-0.5 -top-0.5 rounded-full bg-bad px-1.5 text-[11px] font-semibold text-white">{unread}</span>}
          </button>
        </header>
        {meta.error && <div className="mx-4 mt-4 rounded-lg border border-bad/30 bg-bad-50 p-3 text-sm text-bad sm:mx-6">Backend unreachable: {meta.error}. Run <code>uvicorn main:app --reload</code> in /backend.</div>}
        <main className="mx-auto w-full max-w-[1500px] flex-1 p-4 sm:p-6">
          <Routes>
            {role === 'coordinator' ? (
              <>
                <Route path="/" element={<CommandCenter />} />
                <Route path="/offers" element={<Offers />} />
                <Route path="/data" element={<DataManagement />} />
                <Route path="/details" element={<Details />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/consults" element={<Navigate to="/details" />} />
                <Route path="/physicians" element={<Navigate to="/details" />} />
              </>
            ) : <Route path="/" element={<Navigate to="/approvals" replace />} />}
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/coverage" element={<Coverage />} />
            <Route path="/decide/:incidentId" element={<Decision />} />
            <Route path="/activity" element={<ActivityLog />} />
            <Route path="*" element={<Navigate to={home} replace />} />
          </Routes>
        </main>
      </div>
      {bell && (
        <div className="fixed inset-0 z-40 bg-navy/30" onClick={() => setBell(false)}>
          <div className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <h3 className="font-semibold text-navy">Notifications</h3>
              <div className="flex items-center gap-2">
                <button className="text-xs text-teal-600" onClick={async () => { await api.post(`/api/notifications/read?audience=${role}`); announceChange() }}>Mark all read</button>
                <button aria-label="Close" onClick={() => setBell(false)}><X className="h-5 w-5 text-ink-faint" /></button>
              </div>
            </div>
            <div className="flex-1 divide-y divide-line overflow-auto">
              {(notes.data?.notifications ?? []).length === 0 && <p className="p-6 text-sm text-ink-soft">No notifications yet. Alerts appear here when the system finds something or an offer changes.</p>}
              {(notes.data?.notifications ?? []).map((n: Any) => (
                <button key={n.id} onClick={() => { if (n.link) nav(n.link); setBell(false); api.post(`/api/notifications/read?nid=${n.id}`) }}
                  className={`block w-full px-4 py-3 text-left hover:bg-canvas ${n.read ? '' : 'bg-teal-50/60'}`}>
                  <div className="flex items-center gap-2">
                    {!n.read && <span className="h-2 w-2 rounded-full bg-teal" />}
                    <span className="flex-1 text-sm font-medium">{n.title}</span>
                    <Badge tone={n.severity === 'critical' ? 'critical' : n.severity === 'warning' ? 'warning' : n.severity === 'success' ? 'ok' : 'neutral'}>{n.kind}</Badge>
                  </div>
                  <p className="mt-0.5 text-xs text-ink-soft">{n.body}</p>
                  <p className="num mt-0.5 text-[11px] text-ink-faint">{wall(n.created)}</p>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastHost>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/m" element={<PhysicianApp />} />
            <Route path="/m/*" element={<Navigate to="/m" replace />} />
            <Route path="/*" element={<Shell />} />
          </Routes>
        </AuthProvider>
      </ToastHost>
    </BrowserRouter>
  )
}
