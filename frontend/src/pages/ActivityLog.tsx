import { useState } from 'react'
import { type Any, t, wallDate } from '../api'
import { Badge, Empty, ErrorNote, Loading, PageHeader, Panel, Select, usePoll } from '../ui'

export default function ActivityLog() {
  const [q, setQ] = useState('')
  const [action, setAction] = useState('')
  const [entity, setEntity] = useState('')
  const p = new URLSearchParams()
  if (q) p.set('q', q)
  if (action) p.set('action', action)
  if (entity) p.set('entity', entity)
  const { data, error } = usePoll<Any>(`/api/activity?${p}`, 4000)
  if (error && !data) return <ErrorNote text={error} />
  if (!data) return <Loading />
  const actions = ['offer_proposed', 'offer_approved_and_sent', 'offer_rejected', 'offer_accepted', 'offer_declined', 'offer_timed_out',
    'offer_acceptance_superseded', 'offer_withdrawn_gap_filled', 'consult_reassigned', 'escalation_requested', 'escalation_created',
    'escalation_authorized', 'escalation_rejected', 'internal_alert_sent', 'dataset_loaded', 'event_injected', 'demo_reset', 'assumptions_changed', 'gap_closed']
  return (
    <div>
      <PageHeader title="Activity log" lede="Every flag acted on, decision and offer: who was considered, who was excluded and why, who approved, and the outcome. Stored in activity_log.json.">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" aria-label="Search activity" className="w-44 rounded-lg border border-line bg-white px-3 py-1.5 text-sm" />
        <Select label="Action" value={action} onChange={setAction}><option value="">All actions</option>{actions.map((a) => <option key={a} value={a}>{a.replaceAll('_', ' ')}</option>)}</Select>
        <Select label="Entity" value={entity} onChange={setEntity}><option value="">All records</option>{['offer', 'consult', 'escalation', 'incident', 'dataset', 'event', 'physician', 'config'].map((a) => <option key={a}>{a}</option>)}</Select>
      </PageHeader>
      <Panel pad={false} title={`${data.total} entries`}>
        {data.activity.length === 0 && <div className="p-4"><Empty>No activity yet. Actions taken in the command center appear here.</Empty></div>}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs text-ink-soft">
              <tr>{['When', 'Scenario', 'Actor', 'Action', 'Record', 'Status change', 'Details'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.activity.map((a: Any) => (
                <tr key={a.id} className="align-top">
                  <td className="num whitespace-nowrap px-3 py-2">{wallDate(a.ts)}</td>
                  <td className="num px-3 py-2">{t(a.scenario_time)}</td>
                  <td className="px-3 py-2">{a.actor}<div className="text-xs text-ink-soft">{a.role}</div></td>
                  <td className="px-3 py-2"><Badge tone="info">{a.action.replaceAll('_', ' ')}</Badge></td>
                  <td className="px-3 py-2">{a.entity} <span className="num font-medium">{a.entity_id}</span></td>
                  <td className="px-3 py-2 text-xs">{a.from || a.to ? `${a.from ?? '—'} → ${typeof a.to === 'string' ? a.to : '…'}` : ''}</td>
                  <td className="max-w-md px-3 py-2 text-xs text-ink-soft">
                    {a.details && typeof a.details === 'object' ? Object.entries(a.details).map(([k, v]) => (
                      <div key={k}><span className="font-medium text-ink">{k.replaceAll('_', ' ')}:</span> {typeof v === 'object' ? (v && !Array.isArray(v) ? Object.entries(v as Any).map(([n, r]) => `${n} (${Array.isArray(r) ? r.join('; ') : r})`).join(' · ') : JSON.stringify(v)) : String(v)}</div>
                    )) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
