import { useState } from 'react'
import { AlertTriangle, Search } from 'lucide-react'
import { type Any, t } from '../api'
import { Badge, ErrorNote, Loading, PageHeader, Panel, usePoll } from '../ui'

function stateTone(p: Any) {
  if (p.unavailable) return 'critical'
  if (p.busy) return 'warning'
  if (!p.on_shift) return 'neutral'
  return p.verified ? 'ok' : 'warning'
}

export default function Physicians({ embedded }: { embedded?: boolean } = {}) {
  const { data, error } = usePoll<Any>('/api/physicians', 5000)
  const [q, setQ] = useState('')
  if (error && !data) return <ErrorNote text={error} />
  if (!data) return <Loading />
  const m = (s: string) => s.toLowerCase().includes(q.toLowerCase())
  const on = data.on_shift.filter((p: Any) => m(p.name + p.physician_id))
  const off = data.off_shift.filter((p: Any) => m(p.name + p.physician_id))
  const all = [...data.on_shift.filter((p: Any) => p.kind === 'scheduled'), ...data.off_shift]

  return (
    <div>
      {!embedded && (
      <PageHeader title="Physicians" lede="Derived state reconciles four signals: self-reported status, Synapse call/video, camera, and the desktop agent heartbeat. Availability is inferred, not reported.">
        <label className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name or ID" aria-label="Search physicians"
            className="w-56 rounded-lg border border-line bg-white py-2 pl-8 pr-3 text-sm" />
        </label>
      </PageHeader>
      )}

      <Panel pad={false} title={`On shift (${on.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs text-ink-soft">
              <tr>{['Physician', 'Shift', 'Self-reported', 'Synapse', 'Camera', 'Agent', 'Derived state', 'Consults', 'Calls', 'Open', 'Credentialed'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {on.map((p: Any) => (
                <tr key={p.physician_id + p.kind} className="align-top">
                  <td className="px-3 py-2"><div className="font-medium">{p.name}</div><div className="text-xs text-ink-soft">{p.physician_id}{p.kind === 'split_shift' && <Badge tone="teal" className="ml-1">split shift · seeded {p.seed_count}</Badge>}</div></td>
                  <td className="num px-3 py-2">{p.shift_label}<div className="text-xs text-ink-soft">{p.minutes_to_shift_end != null ? `${p.minutes_to_shift_end} min left` : t(p.shift_start) + ' start'}</div></td>
                  <td className="px-3 py-2">{p.self_reported_status}</td>
                  <td className="px-3 py-2">{p.synapse_session ? 'Active' : '—'}</td>
                  <td className="px-3 py-2">{p.desktop_agent === 'Offline' ? <span className="text-ink-faint">unknown</span> : p.camera ? 'Active' : '—'}</td>
                  <td className="px-3 py-2"><Badge tone={p.desktop_agent === 'Online' ? 'ok' : 'warning'}>{p.desktop_agent}</Badge></td>
                  <td className="px-3 py-2">
                    <Badge tone={stateTone(p) as Any}>{p.derived_state}</Badge>
                    {p.flags.map((f: Any) => <p key={f.code} className="mt-1 flex max-w-xs gap-1 text-xs text-warn"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{f.message}</p>)}
                    {p.ringing && <p className="mt-1 text-xs text-warn">Phone ringing ({p.ringing})</p>}
                  </td>
                  <td className="num px-3 py-2 text-right">{p.consults_this_shift}</td>
                  <td className="num px-3 py-2 text-right">{p.calls_this_shift}</td>
                  <td className="num px-3 py-2 text-right">{p.open_consults}{p.open_notes > 0 && <div className="text-xs text-ink-soft">{p.open_notes} notes</div>}</td>
                  <td className="px-3 py-2 text-xs">{p.credentialed.length} · {p.credentialed.map((h: string) => h.replace('SYN-', '')).join(' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel className="mt-5" pad={false} title={`Off-shift roster (${off.length})`} subtitle="Split-shift eligibility is evaluated per gap on the decision card.">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs text-ink-soft">
              <tr>{['Physician', 'Role', 'Opt-in', 'Last shift ended', 'Next shift', 'Hours (7d)', 'Online in', 'Channel', 'Declined (30d)', 'Credentialed'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {off.map((p: Any) => (
                <tr key={p.physician_id}>
                  <td className="px-3 py-2"><div className="font-medium">{p.name}</div><div className="text-xs text-ink-soft">{p.physician_id}{p.joined_split_shift && <Badge tone="ok" className="ml-1">joining</Badge>}</div></td>
                  <td className="px-3 py-2">{p.role}</td>
                  <td className="px-3 py-2"><Badge tone={String(p.split_shift_opt_in).toLowerCase().startsWith('y') ? 'ok' : 'neutral'}>{p.split_shift_opt_in}</Badge></td>
                  <td className="num px-3 py-2">{p.last_shift_end?.slice(5, 16).replace('T', ' ')}</td>
                  <td className="num px-3 py-2">{p.next_shift_start?.slice(5, 16).replace('T', ' ')}</td>
                  <td className="num px-3 py-2 text-right">{p.hours_worked_last_7d}</td>
                  <td className="num px-3 py-2 text-right">{p.est_minutes_to_online} min</td>
                  <td className="px-3 py-2">{p.preferred_channel}</td>
                  <td className="num px-3 py-2 text-right">{p.offers_declined_last_30d}</td>
                  <td className="px-3 py-2 text-xs">{p.credentialed.map((h: string) => h.replace('SYN-', '')).join(' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel className="mt-5" pad={false} title="Credentialing matrix" subtitle="Uneven workload often traces back to here rather than to effort.">
        <div className="overflow-x-auto">
          <table className="text-xs">
            <thead><tr><th className="sticky left-0 bg-white px-3 py-2 text-left font-medium text-ink-soft">Physician</th>
              {data.hospitals.map((h: Any) => <th key={h.hospital_id} className="px-1.5 py-2 font-medium text-ink-soft" title={h.hospital_name}>{h.hospital_id.replace('SYN-', '')}</th>)}
              <th className="px-3 py-2 text-ink-soft">Total</th></tr></thead>
            <tbody className="divide-y divide-line">
              {all.map((p: Any) => (
                <tr key={p.physician_id}>
                  <td className="sticky left-0 whitespace-nowrap bg-white px-3 py-1.5 font-medium">{p.name} <span className="text-ink-faint">{p.on_shift === undefined ? 'off' : 'on'}</span></td>
                  {data.hospitals.map((h: Any) => <td key={h.hospital_id} className="px-1.5 py-1.5 text-center">{p.credentialed.includes(h.hospital_id) ? <span className="inline-block h-3 w-3 rounded-sm bg-teal" aria-label="credentialed" /> : <span className="inline-block h-3 w-3 rounded-sm bg-canvas" />}</td>)}
                  <td className="num px-3 py-1.5 text-center">{p.credentialed.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
