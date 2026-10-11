import { createContext, useContext, useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity, Bell, ClipboardCheck, Database, Gauge, LayoutGrid, Menu, Send, Settings as Cog, Smartphone, Users, X,
} from 'lucide-react'
import { api, wall, type Any } from './api'
import { Badge, ToastHost, announceChange, usePoll } from './ui'
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

export type Role = 'coordinator' | 'clinical_lead'
type RoleCtx = { role: Role; setRole: (r: Role) => void; actor: string }
const Ctx = createContext<RoleCtx>({ role: 'coordinator', setRole: () => {}, actor: 'Ops Coordinator' })
export const useRole = () => useContext(Ctx)
const ACTOR: Record<Role, string> = { coordinator: 'Ops Coordinator', clinical_lead: 'Clinical Lead on Duty' }

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
  const [role, setRoleState] = useState<Role>(() => (localStorage.getItem('sevaro.role') as Role) || 'coordinator')
  const [menu, setMenu] = useState(false)
  const [bell, setBell] = useState(false)
  const nav = useNavigate()
  const loc = useLocation()
  const meta = usePoll<Any>('/api/meta', 5000)
  const notes = usePoll<Any>(`/api/notifications?audience=${role}`, 4000)
  const approvals = usePoll<Any>('/api/offers?status=proposed', 4000)
  const setRole = (r: Role) => {
    setRoleState(r)
    try { localStorage.setItem('sevaro.role', r) } catch { /* storage unavailable */ }
    nav(r === 'clinical_lead' ? '/approvals' : '/')
  }
  useEffect(() => setMenu(false), [loc.pathname])
  const pending = (approvals.data?.offers?.length ?? 0) + (approvals.data?.escalations?.filter((e: Any) => e.status === 'pending').length ?? 0)
  const unread = notes.data?.unread ?? 0

  const side = (
    <nav className="flex h-full flex-col bg-navy text-white">
      <div className="px-5 pb-5 pt-6">
        <div className="text-lg font-semibold tracking-tight">Sevaro</div>
        <div className="text-[13px] text-white/60">Operations command center</div>
      </div>
      <div className="flex-1 space-y-0.5 px-3">
        {NAV[role].map((n) => (
          <NavLink key={n.to + n.label} to={n.to} end={n.to === '/'}
            className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-white/12 bg-white/10 font-medium text-white' : 'text-white/70 hover:bg-white/5 hover:text-white'}`}>
            <n.icon className="h-4 w-4" />
            <span className="flex-1">{n.label}</span>
            {n.to === '/approvals' && pending > 0 && <span className="rounded-full bg-warn px-1.5 text-xs font-semibold">{pending}</span>}
          </NavLink>
        ))}
        <a href="/m" target="_blank" rel="noreferrer" className="mt-4 flex items-center gap-3 rounded-lg border border-white/15 px-3 py-2 text-sm text-white/80 hover:bg-white/5">
          <Smartphone className="h-4 w-4" />Doctor's phone view
        </a>
      </div>
      <p className="m-4 text-xs leading-relaxed text-white/50">Prototype · synthetic data only</p>
    </nav>
  )

  return (
    <Ctx.Provider value={{ role, setRole, actor: ACTOR[role] }}>
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
            <div className="min-w-0 flex-1">
              <div className="num truncate text-sm font-semibold text-navy">{meta.data?.as_of_label ?? '…'}</div>
              <div className="truncate text-xs text-ink-soft">{meta.data?.dataset ?? 'connecting'}</div>
            </div>
            <label className="hidden text-xs text-ink-soft sm:block" htmlFor="role">Viewing as</label>
            <select id="role" value={role} onChange={(e) => setRole(e.target.value as Role)}
              className="max-w-[9.5rem] rounded-lg border border-line bg-white px-2 py-1.5 text-sm font-medium text-navy sm:max-w-none">
              <option value="coordinator">Coordinator</option>
              <option value="clinical_lead">Clinical lead</option>
            </select>
            {role === 'coordinator' && <NavLink to="/settings" aria-label="Settings" className="rounded-lg p-2 hover:bg-canvas"><Cog className="h-5 w-5 text-navy" /></NavLink>}
            <button aria-label="Notifications" onClick={() => setBell(true)} className="relative rounded-lg p-2 hover:bg-canvas">
              <Bell className="h-5 w-5 text-navy" />
              {unread > 0 && <span className="num absolute -right-0.5 -top-0.5 rounded-full bg-bad px-1.5 text-[11px] font-semibold text-white">{unread}</span>}
            </button>
          </header>
          {meta.error && <div className="mx-4 mt-4 rounded-lg border border-bad/30 bg-bad-50 p-3 text-sm text-bad sm:mx-6">Backend unreachable: {meta.error}. Run <code>uvicorn main:app --reload</code> in /backend.</div>}
          <main className="mx-auto w-full max-w-[1500px] flex-1 p-4 sm:p-6">
            <Routes>
              <Route path="/" element={<CommandCenter />} />
              <Route path="/coverage" element={<Coverage />} />
              <Route path="/decide/:incidentId" element={<Decision />} />
              <Route path="/details" element={<Details />} />
              <Route path="/consults" element={<Navigate to="/details" />} />
              <Route path="/physicians" element={<Navigate to="/details" />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/offers" element={<Offers />} />
              <Route path="/activity" element={<ActivityLog />} />
              <Route path="/data" element={<DataManagement />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
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
              {(notes.data?.notifications ?? []).length === 0 && <p className="p-6 text-sm text-ink-soft">No notifications yet. Alerts appear here when the system detects something or an offer changes state.</p>}
              {(notes.data?.notifications ?? []).map((n: Any) => (
                <button key={n.id} onClick={() => { if (n.link) nav(n.link); setBell(false); api.post(`/api/notifications/read?nid=${n.id}`) }}
                  className={`block w-full px-4 py-3 text-left hover:bg-canvas ${n.read ? '' : 'bg-teal-50/50'}`}>
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
    </Ctx.Provider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastHost>
        <Routes>
          <Route path="/m" element={<PhysicianApp />} />
          <Route path="/m/:physicianId" element={<PhysicianApp />} />
          <Route path="/*" element={<Shell />} />
        </Routes>
      </ToastHost>
    </BrowserRouter>
  )
}
