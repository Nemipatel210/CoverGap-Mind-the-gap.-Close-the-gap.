import { Lock } from 'lucide-react'
import { api, type Any } from '../api'
import { useRole } from '../App'
import { Badge, ErrorNote, Loading, PageHeader, Panel, Select, useAction, usePoll } from '../ui'

export default function Settings() {
  const { actor } = useRole()
  const { data, error } = usePoll<Any>('/api/config', 15000)
  const meta = usePoll<Any>('/api/meta', 15000)
  const { run } = useAction()
  if (error && !data) return <ErrorNote text={error} />
  if (!data || !meta.data) return <Loading />
  const P = data.preferences.coordinator
  const A = data.assumptions
  const setPref = (patch: Any) => run('p', () => api.put('/api/preferences/coordinator', patch), 'Preferences saved')
  const setA = (patch: Any) => run('a', () => api.put('/api/config/assumptions', { ...patch, actor }), 'Projection assumptions updated')
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])

  return (
    <div>
      <PageHeader title="Settings" lede="Coordinator preferences change what you see and how options are ranked. Safety rules are fixed." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Coordinator view preferences">
          <fieldset className="mb-4">
            <legend className="mb-1.5 text-sm font-medium">Severities in the attention queue</legend>
            <div className="flex flex-wrap gap-3 text-sm">
              {['critical', 'warning', 'info'].map((s) => (
                <label key={s} className="flex items-center gap-1.5"><input type="checkbox" className="accent-teal" checked={P.severities.includes(s)} onChange={() => setPref({ severities: toggle(P.severities, s) })} />{s}</label>
              ))}
            </div>
          </fieldset>
          <fieldset className="mb-4">
            <legend className="mb-1.5 text-sm font-medium">Hospitals to watch <span className="font-normal text-ink-soft">(none selected = all)</span></legend>
            <div className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
              {meta.data.hospitals.map((h: Any) => (
                <label key={h.hospital_id} className="flex items-center gap-1.5"><input type="checkbox" className="accent-teal" checked={P.hospitals.includes(h.hospital_id)} onChange={() => setPref({ hospitals: toggle(P.hospitals, h.hospital_id) })} />{h.hospital_name}</label>
              ))}
            </div>
          </fieldset>
          <label className="block text-sm font-medium">Default ranking for split-shift candidates
            <Select className="mt-1 block w-full" label="Ranking" value={P.ranking} onChange={(v) => setPref({ ranking: v })}>
              <option value="fastest">Fastest coverage</option><option value="lightest_load">Lightest load on joining physician</option><option value="fewest_offers">Fewest offers per physician</option>
            </Select>
          </label>
        </Panel>

        <Panel title="Projection assumptions" subtitle="Where the brief is silent, these choices are explicit and editable.">
          <div className="space-y-3 text-sm">
            <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 accent-teal" checked={A.count_scheduled_starts} onChange={(e) => setA({ count_scheduled_starts: e.target.checked })} />
              <span><span className="font-medium">Scheduled shift starts count toward coverage</span><span className="block text-ink-soft">Proposal default. A night physician starting at 19:00 covers from 19:00 but is never a split-shift candidate.</span></span></label>
            <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 accent-teal" checked={A.unavailable_persists} onChange={(e) => setA({ unavailable_persists: e.target.checked })} />
              <span><span className="font-medium">Temporarily Unavailable persists through the horizon</span><span className="block text-ink-soft">Conservative: assume they don't come back unless the stream says so.</span></span></label>
            <label className="flex items-center justify-between gap-2"><span className="font-medium">Projection horizon</span>
              <Select label="Horizon" value={String(A.horizon_min)} onChange={(v) => setA({ horizon_min: Number(v) })}>{[90, 120, 150, 180].map((m) => <option key={m} value={m}>{m} minutes</option>)}</Select></label>
            <label className="flex items-center justify-between gap-2"><span className="font-medium">Wall-clock offer timeout</span>
              <Select label="Timeout" value={String(A.offer_timeout_wall_min)} onChange={(v) => setA({ offer_timeout_wall_min: Number(v) })}>{[2, 5, 10].map((m) => <option key={m} value={m}>{m} minutes</option>)}</Select></label>
            <label className="flex items-center justify-between gap-2"><span className="font-medium">AI-assisted call if no reply after</span>
              <Select label="AI call delay" value={String(A.ai_call_after_sec)} onChange={(v) => setA({ ai_call_after_sec: Number(v) })}>{[30, 60, 120, 300].map((m) => <option key={m} value={m}>{m < 60 ? `${m} seconds` : `${m / 60} minute${m > 60 ? 's' : ''}`}</option>)}</Select></label>
            <label className="flex items-center justify-between gap-2"><span className="font-medium">Simulator: minutes a consult keeps a physician busy</span>
              <Select label="Service minutes" value={String(A.sim_service_min)} onChange={(v) => setA({ sim_service_min: Number(v) })}>{[15, 20, 25, 30, 40].map((m) => <option key={m} value={m}>{m} min</option>)}</Select></label>
          </div>
        </Panel>

        <Panel className="lg:col-span-2" title={<span className="flex items-center gap-2"><Lock className="h-4 w-4" />Safety rules (fixed)</span>} subtitle="From the challenge brief. Not adjustable from the UI.">
          <div className="grid gap-5 md:grid-cols-3">
            <div>
              <h3 className="mb-2 text-sm font-semibold text-navy">Split-shift eligibility</h3>
              <ul className="space-y-1 text-sm">
                <li>Opted in to split-shift offers</li><li>Credentialed at a gap hospital</li>
                <li>≥ {data.split_shift.min_rest_hours}h since last shift, at offered start</li>
                <li>7-day hours + offer ≤ {data.split_shift.max_hours_7d}</li><li>No overlap with a scheduled shift</li>
                <li>Offers ≥ {data.split_shift.min_offer_hours}h; expire after {data.split_shift.offer_expiry_min} min</li>
                <li>One open offer per physician; ≤ {data.split_shift.max_offers_per_week} per week</li>
                <li>Clinical-lead approval before any message</li><li>No patient information in notifications</li>
              </ul>
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold text-navy">Routing model</h3>
              <ul className="space-y-1 text-sm">
                <li>On shift and credentialed at the calling hospital</li><li>Not busy, not ringing, no call ended &lt; {data.routing.recent_call_block_min} min ago</li>
                <li>Low volume priority: ≤ {data.routing.low_volume_day} day / ≤ {data.routing.low_volume_night} night</li>
                <li>Otherwise fewest consults; ties to least recently answered</li><li>Failed attempts retry every {data.routing.retry_min} min</li>
              </ul>
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold text-navy">Time standards (warning / critical)</h3>
              <ul className="space-y-1 text-sm">
                {data.standards.map((s: Any) => <li key={s.key} className="flex justify-between gap-2"><span>{s.label} <Badge>{s.applies}</Badge></span><span className="num whitespace-nowrap">{s.warning} / {s.critical}m</span></li>)}
                <li className="flex justify-between gap-2"><span>Open notes within 60 min of shift end</span><span className="whitespace-nowrap">any / 2+</span></li>
              </ul>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  )
}
