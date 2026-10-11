import { useMemo, useState } from 'react'
import { type Any, t, tSec } from '../api'
import { Badge, ErrorNote, Loading, PageHeader, Panel, Select, sevTone, usePoll } from '../ui'

const STAGE_COLOR: Record<string, string> = {
  Received: '#D9DFE7', Triaged: '#C3CCD8', Assigned: '#93A3B8', 'Provider Contacted': '#6B7F99',
  'CT/CTA or Imaging Pending': '#D99A3D', 'Imaging Review': '#EBC27E', 'Video Consult In Progress': '#13294B',
  'Note Pending': '#B9CFE6', Documentation: '#7FA6CC',
}
const ACT_COLOR: Record<string, string> = { call: '#2A7477', video: '#13294B', camera: '#A86A12' }

function TimerBar({ tm }: { tm: Any }) {
  const max = tm.critical * 1.25
  const w = Math.min(100, (tm.minutes / max) * 100)
  const c = tm.level === 'critical' ? 'bg-bad' : tm.level === 'warning' ? 'bg-warn' : 'bg-teal'
  return (
    <div className="w-36" title={`${tm.label}: ${tm.minutes} min (warning ${tm.warning}, critical ${tm.critical})`}>
      <div className="relative h-2 rounded-full bg-canvas">
        <div className={`absolute inset-y-0 left-0 rounded-full ${c}`} style={{ width: `${w}%` }} />
        <div className="absolute inset-y-[-2px] w-px bg-warn" style={{ left: `${(tm.warning / max) * 100}%` }} />
        <div className="absolute inset-y-[-2px] w-px bg-bad" style={{ left: `${(tm.critical / max) * 100}%` }} />
      </div>
      <div className="num mt-0.5 text-[11px] text-ink-soft">{tm.minutes}m / {tm.warning}·{tm.critical}</div>
    </div>
  )
}

export default function Consults({ embedded }: { embedded?: boolean } = {}) {
  const { data, error } = usePoll<Any>('/api/consults', 5000)
  const [level, setLevel] = useState('all')
  const [type, setType] = useState('all')
  const [phys, setPhys] = useState('all')
  const rows = useMemo(() => (data?.consults ?? []).filter((c: Any) =>
    (level === 'all' || c.level === level) && (type === 'all' || c.consult_type === type) &&
    (phys === 'all' || (phys === 'none' ? !c.physician_id : c.physician_id === phys))), [data, level, type, phys])
  if (error && !data) return <ErrorNote text={error} />
  if (!data) return <Loading />
  const tl = data.timeline
  const t0 = new Date(tl.start).getTime(), t1 = new Date(tl.end).getTime()
  const pct = (iso: string) => ((new Date(iso).getTime() - t0) / (t1 - t0)) * 100
  const ticks = Array.from({ length: 7 }, (_, i) => new Date(t0 + ((t1 - t0) * i) / 6).toISOString())
  const physIds = [...new Set(data.consults.map((c: Any) => c.physician_id).filter(Boolean))] as string[]
  const focus = phys !== 'all' && phys !== 'none' ? phys : null
  const focusConsults = focus ? tl.consults.filter((c: Any) => c.physician_id === focus && c.stage !== 'Signed Off') : []

  return (
    <div>
      {!embedded && (
      <PageHeader title="Consults & physician activity" lede="Consult lifecycle and physician activity are tracked separately: one physician can be on video for one consult while another waits in imaging review and a third has a note pending." />
      )}
      <Panel pad={false} title={`Open consults (${rows.length})`} action={
        <div className="flex flex-wrap gap-2">
          <Select label="Timer level" value={level} onChange={setLevel}><option value="all">All timer levels</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="ok">Within standard</option></Select>
          <Select label="Type" value={type} onChange={setType}><option value="all">All types</option>{[...new Set(data.consults.map((c: Any) => c.consult_type))].map((x) => <option key={x as string}>{x as string}</option>)}</Select>
          <Select label="Physician" value={phys} onChange={setPhys}><option value="all">All physicians</option><option value="none">Unassigned</option>{physIds.sort().map((p) => <option key={p} value={p}>{p}</option>)}</Select>
        </div>}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs text-ink-soft">
              <tr>{['Consult', 'Hospital', 'Type', 'Physician', 'Stage', 'Entered', 'Received', 'Against standard'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((c: Any) => (
                <tr key={c.consult_id} className="align-top">
                  <td className="num whitespace-nowrap px-3 py-2 font-medium">{c.consult_id}{c.reassigned_by_command_center && <div><Badge tone="teal">reassigned here</Badge></div>}</td>
                  <td className="px-3 py-2">{c.hospital_name}</td>
                  <td className="px-3 py-2">{c.consult_type === 'Stroke' ? <span className="font-medium text-bad">Stroke</span> : c.consult_type}</td>
                  <td className="px-3 py-2">{c.physician_name ?? <span className="font-medium text-bad">Unassigned</span>}
                    {c.physician_state && <div className="text-xs text-ink-soft">{c.physician_state}</div>}
                    {c.routing_failures > 0 && <div className="text-xs text-bad">{c.routing_failures} routing failures</div>}
                    {c.ringing_to && <div className="text-xs text-warn">ringing {c.ringing_to}</div>}</td>
                  <td className="px-3 py-2">{c.current_stage}</td>
                  <td className="num px-3 py-2">{tSec(c.stage_entered_at)}<div className="text-xs text-ink-soft">{c.minutes_in_stage} min</div></td>
                  <td className="num px-3 py-2">{c.minutes_since_received} min ago</td>
                  <td className="px-3 py-2">
                    {c.timers.length === 0 ? <span className="text-xs text-ink-faint">No standard for this stage/type</span> :
                      c.timers.map((tm: Any) => <div key={tm.standard} className="flex items-center gap-2"><TimerBar tm={tm} /><Badge tone={tm.level === 'ok' ? 'ok' : sevTone(tm.level)}>{tm.level === 'ok' ? 'OK' : tm.level}</Badge></div>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel className="mt-5" title="Activity lanes, last 3 hours" subtitle="Built from the event stream. Pick a physician above to see their consults move through stages underneath.">
        <div className="overflow-x-auto">
          <div className="min-w-[760px]">
            <div className="relative ml-36 h-5 text-[11px] text-ink-faint">
              {ticks.map((x) => <span key={x} className="num absolute -translate-x-1/2" style={{ left: `${pct(x)}%` }}>{new Date(x).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' })}</span>)}
            </div>
            {tl.physicians.filter((p: Any) => p.segments.length).map((p: Any) => (
              <div key={p.physician_id} className="flex items-center border-t border-line py-1.5">
                <button className="w-36 shrink-0 truncate pr-2 text-left text-xs font-medium hover:text-teal-600" onClick={() => setPhys(p.physician_id)}>{p.physician_id} {p.name.replace('Dr. ', '')}</button>
                <div className="relative h-5 flex-1 rounded bg-canvas">
                  {p.segments.map((s: Any, i: number) => (
                    <div key={i} title={`${s.kind}${s.consult_id ? ' · ' + s.consult_id : ''} ${tSec(s.start)}–${s.open ? 'now' : tSec(s.end)}`}
                      className={`absolute rounded-sm text-[10px] leading-5 text-white ${s.kind === 'camera' ? 'top-[14px] h-1.5' : 'inset-y-0'}`}
                      style={{ left: `${pct(s.start)}%`, width: `${Math.max(0.4, pct(s.end) - pct(s.start))}%`, background: ACT_COLOR[s.kind] }}>
                      {s.kind !== 'camera' && pct(s.end) - pct(s.start) > 4 ? <span className="px-1">{s.consult_id?.replace('CON-', '')}</span> : null}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {focusConsults.map((c: Any) => (
              <div key={c.consult_id} className="flex items-center border-t border-dashed border-line py-1.5">
                <div className="w-36 shrink-0 truncate pr-2 text-xs text-ink-soft">{c.consult_id} · {c.hospital_name}</div>
                <div className="relative h-4 flex-1">
                  {c.segments.map((s: Any, i: number) => (
                    <div key={i} title={`${s.stage} ${tSec(s.start)}–${tSec(s.end)}`} className="absolute inset-y-0"
                      style={{ left: `${pct(s.start)}%`, width: `${Math.max(0.3, pct(s.end) - pct(s.start))}%`, background: STAGE_COLOR[s.stage] ?? '#ccc' }} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-3 text-xs text-ink-soft">
          {Object.entries(ACT_COLOR).map(([k, c]) => <span key={k} className="flex items-center gap-1"><span className="h-3 w-4 rounded-sm" style={{ background: c }} />{k === 'camera' ? 'camera active' : k}</span>)}
          {focus && Object.entries(STAGE_COLOR).map(([k, c]) => <span key={k} className="flex items-center gap-1"><span className="h-3 w-4 rounded-sm" style={{ background: c }} />{k}</span>)}
        </div>
      </Panel>
    </div>
  )
}
