import { useRef, useState } from 'react'
import { CheckCircle2, Download, FileUp, RotateCcw, Trash2, Upload, XCircle, Zap } from 'lucide-react'
import { api, type Any, wall } from '../api'
import { useRole } from '../App'
import { Badge, Button, ErrorNote, Loading, Modal, PageHeader, Panel, Select, announceChange, useAction, usePoll, useToast } from '../ui'

function IssueList({ issues }: { issues: Any[] }) {
  if (!issues?.length) return <p className="flex items-center gap-1 text-xs text-ok"><CheckCircle2 className="h-3.5 w-3.5" />No issues found</p>
  return (
    <ul className="space-y-0.5 text-xs">
      {issues.map((i, k) => (
        <li key={k} className={i.level === 'error' ? 'text-bad' : 'text-warn'}>
          {i.level === 'error' ? 'Error' : 'Warning'}{i.row ? ` (row ${i.row})` : ''}: {i.message}
        </li>
      ))}
    </ul>
  )
}

export default function FullDataset() {
  const { actor } = useRole()
  const types = usePoll<Any>('/api/datasets/types', 5000)
  const snap = usePoll<Any>('/api/snapshot-check', 8000)
  const meta = usePoll<Any>('/api/meta', 8000)
  const [dtype, setDtype] = useState('auto')
  const [mode, setMode] = useState<'replace' | 'append_events'>('replace')
  const composed = usePoll<Any>(`/api/datasets/composed?mode=${mode}`, 6000)
  const [report, setReport] = useState<Any>(null)
  const [drag, setDrag] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [label, setLabel] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const { run, busy } = useAction()
  const toast = useToast()

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files)
    if (!list.length) return
    const fd = new FormData()
    list.forEach((f) => fd.append('files', f))
    fd.append('dataset_type', dtype)
    setUploading(true)
    try {
      const r = await api.upload('/api/datasets/validate', fd)
      setReport(r)
      const bad = r.files.filter((f: Any) => !f.ok).length
      toast(bad ? 'error' : 'success', bad ? `${bad} of ${r.files.length} file(s) failed validation` : `${r.files.length} file(s) validated and staged`)
      announceChange()
    } catch (e) {
      toast('error', (e as Error).message)
    } finally {
      setUploading(false)
      if (input.current) input.current.value = ''
    }
  }

  if (types.error && !types.data) return <ErrorNote text={types.error} />
  if (!types.data) return <Loading />
  const staging = types.data.staging ?? {}
  const stagedTypes = Object.keys(staging)
  const C = composed.data

  return (
    <div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-5">
          <Panel title="1. Upload and validate" subtitle="CSV or JSON (array of records). Drop several files at once; the type is detected from the file name or columns.">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <label className="text-sm text-ink-soft" htmlFor="dtype">Dataset type</label>
              <Select label="Dataset type" value={dtype} onChange={setDtype}>
                <option value="auto">Auto-detect from file</option>
                {types.data.types.map((t: Any) => <option key={t.type} value={t.type}>{t.label}{t.required ? '' : ' (optional)'}</option>)}
              </Select>
            </div>
            <div onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}
              className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center ${drag ? 'border-teal bg-teal-50' : 'border-line bg-canvas/50'}`}>
              <FileUp className="h-8 w-8 text-teal-600" />
              <p className="mt-2 text-sm font-medium">Drop files here</p>
              <p className="text-xs text-ink-soft">or</p>
              <Button className="mt-2" variant="secondary" busy={uploading} onClick={() => input.current?.click()}><Upload className="h-4 w-4" />Choose files</Button>
              <input ref={input} type="file" multiple accept=".csv,.json,.txt" className="hidden" onChange={(e) => e.target.files && upload(e.target.files)} aria-label="Choose dataset files" />
            </div>

            {report && (
              <div className="mt-4 space-y-3">
                {report.files.map((f: Any, i: number) => (
                  <div key={i} className={`rounded-lg border p-3 ${f.ok ? 'border-ok/30' : 'border-bad/30 bg-bad-50/30'}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      {f.ok ? <CheckCircle2 className="h-4 w-4 text-ok" /> : <XCircle className="h-4 w-4 text-bad" />}
                      <span className="font-medium">{f.filename}</span>
                      {f.label && <Badge tone="info">{f.label}</Badge>}
                      {f.rows_in_file != null && <span className="num ml-auto text-xs text-ink-soft">{f.rows_valid} valid of {f.rows_in_file} rows{f.dropped ? ` · ${f.dropped} skipped` : ''}</span>}
                    </div>
                    <div className="mt-1.5"><IssueList issues={f.issues} /></div>
                    {f.preview?.length > 0 && (
                      <details className="mt-2" open={report.files.length === 1}>
                        <summary className="cursor-pointer text-xs text-teal-600">Preview first {f.preview.length} rows</summary>
                        <div className="mt-1 overflow-x-auto">
                          <table className="text-xs">
                            <thead><tr>{Object.keys(f.preview[0]).map((c) => <th key={c} className="whitespace-nowrap border-b border-line px-2 py-1 text-left font-medium text-ink-soft">{c}</th>)}</tr></thead>
                            <tbody>{f.preview.map((r: Any, k: number) => <tr key={k}>{Object.values(r).map((v, j) => <td key={j} className="whitespace-nowrap border-b border-line px-2 py-1">{String(v)}</td>)}</tr>)}</tbody>
                          </table>
                        </div>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="2. Review staged files and load" action={stagedTypes.length > 0 && <Button size="sm" variant="ghost" onClick={() => run('clr', () => api.del('/api/datasets/staging'), 'Staging cleared').then(() => setReport(null))}><Trash2 className="h-3.5 w-3.5" />Clear staging</Button>}>
            {stagedTypes.length === 0 ? <p className="text-sm text-ink-soft">Nothing staged yet. Validated files appear here before they become active.</p> : (
              <>
                <div className="mb-3 flex flex-wrap gap-2">
                  <label className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${mode === 'replace' ? 'border-teal bg-teal-50' : 'border-line'}`}>
                    <input type="radio" className="mt-1 accent-teal" checked={mode === 'replace'} onChange={() => setMode('replace')} />
                    <span><span className="font-medium">Replace dataset</span><span className="block text-xs text-ink-soft">Staged files replace their type; others are kept. Offers and notifications reset.</span></span>
                  </label>
                  <label className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${mode === 'append_events' ? 'border-teal bg-teal-50' : 'border-line'}`}>
                    <input type="radio" className="mt-1 accent-teal" checked={mode === 'append_events'} onChange={() => setMode('append_events')} />
                    <span><span className="font-medium">Append events (live test)</span><span className="block text-xs text-ink-soft">Adds staged events to the current stream. Duplicates by event_id are ignored. Offers are kept.</span></span>
                  </label>
                </div>
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-ink-soft"><tr><th className="py-1 font-medium">Dataset</th><th className="py-1 font-medium">Source after load</th><th className="py-1 text-right font-medium">Rows</th></tr></thead>
                  <tbody className="divide-y divide-line">
                    {types.data.types.map((t: Any) => (
                      <tr key={t.type}>
                        <td className="py-1.5">{t.label}{staging[t.type] && <span className="block text-xs text-ink-soft">{staging[t.type].filename}</span>}</td>
                        <td className="py-1.5 text-xs">{C?.sources?.[t.type] ? <Badge tone={C.sources[t.type].startsWith('staged') || C.sources[t.type].includes('appended') ? 'teal' : C.sources[t.type].startsWith('dropped') ? 'warning' : 'neutral'}>{C.sources[t.type]}</Badge> : <span className="text-ink-faint">{t.required ? 'missing' : 'none'}</span>}</td>
                        <td className="num py-1.5 text-right">{C?.counts?.[t.type] ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {C && <div className="mt-3"><p className="mb-1 text-xs font-semibold text-navy">Cross-file checks</p><IssueList issues={C.issues} /></div>}
                {mode === 'append_events' && C?.new_events != null && <p className="mt-2 text-sm">{C.new_events} new event(s) will be added.</p>}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {mode === 'replace' && <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Dataset name (optional)" className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm" aria-label="Dataset name" />}
                  <Button className="ml-auto" disabled={!C?.ok} busy={busy === 'load'}
                    onClick={() => run('load', () => api.post('/api/datasets/load', { mode, actor, label: label || undefined }), (r) => `Loaded: ${r.label}`).then((r) => { if (r) { setReport(null); setLabel('') } })}>
                    {mode === 'replace' ? 'Load dataset' : 'Append events'}</Button>
                </div>
                {C && !C.ok && <p className="mt-2 text-sm text-bad">Fix the errors above before loading. The current dataset stays active.</p>}
              </>
            )}
          </Panel>

          <InjectEvent hospitals={meta.data?.hospitals ?? []} asOf={meta.data?.as_of} physicians={[...(meta.data?.on_shift ?? []), ...(meta.data?.off_shift ?? [])]} />
        </div>

        <div className="space-y-5">
          <Panel title="Active dataset">
            <p className="font-medium text-navy">{types.data.active.label}</p>
            <p className="text-xs text-ink-soft">{types.data.active.source === 'demo' ? 'Original synthetic demo data' : `Loaded ${wall(types.data.active.loaded_wall)} · ${types.data.active.mode?.replace('_', ' ')}`}</p>
            <ul className="mt-3 divide-y divide-line text-sm">
              {types.data.types.map((t: Any) => (
                <li key={t.type} className="flex items-center justify-between py-1.5">
                  <span>{t.label}</span>
                  <span className="flex items-center gap-2">
                    <span className="num text-ink-soft">{t.active_rows || '—'}</span>
                    <a href={api.url(`/api/datasets/sample/${t.type}`)} title={`Download demo ${t.label} as a template`} className="text-teal-600"><Download className="h-3.5 w-3.5" /></a>
                  </span>
                </li>
              ))}
            </ul>
            <Button className="mt-4 w-full" variant="secondary" onClick={() => setConfirmReset(true)}><RotateCcw className="h-4 w-4" />Reset to demo data</Button>
          </Panel>
          <Panel title="Replay check" subtitle="Rebuilt state compared with the reference snapshot files, at the snapshot time.">
            {!snap.data ? <Loading /> : snap.data.all_ok === null ? <p className="text-sm text-ink-soft">No reference snapshot in this dataset. Upload snapshot files to verify a replay.</p> : (
              <>
                <p className={`text-2xl font-semibold ${snap.data.all_ok ? 'text-ok' : 'text-bad'}`}><span className="num">{snap.data.matched}/{snap.data.total}</span> fields match</p>
                {snap.data.mismatches.length > 0 && <ul className="mt-2 space-y-0.5 text-xs text-bad">{snap.data.mismatches.slice(0, 8).map((m: Any, i: number) => <li key={i}>{m.entity} {m.field}: expected {m.expected}, got {m.actual ?? '—'}</li>)}</ul>}
              </>
            )}
          </Panel>
          <Panel title="Expected formats">
            <ul className="space-y-2 text-xs">
              {types.data.types.map((t: Any) => (
                <li key={t.type}><span className="font-medium text-ink">{t.label}</span>{!t.required && <span className="text-ink-faint"> (optional)</span>}<span className="block text-ink-soft">{t.columns.join(', ')}{t.dynamic_hospital_columns ? ', + one column per hospital ID' : ''}</span></li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      <Modal open={confirmReset} onClose={() => setConfirmReset(false)} title="Reset to the demo dataset?">
        <p className="text-sm">This restores the original synthetic files and clears offers, escalations, notifications and staged uploads. The activity log is kept.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmReset(false)}>Cancel</Button>
          <Button variant="danger" busy={busy === 'reset'} onClick={() => run('reset', () => api.post('/api/datasets/reset', { actor }), 'Demo dataset restored').then(() => { setConfirmReset(false); setReport(null) })}>Reset demo data</Button>
        </div>
      </Modal>
    </div>
  )
}

const EVENT_TYPES = ['consult_received', 'consult_triaged', 'physician_assigned', 'incoming_call_ringing', 'incoming_call_started', 'incoming_call_ended',
  'outgoing_call_started', 'outgoing_call_ended', 'imaging_requested', 'imaging_returned', 'video_started', 'video_ended', 'note_started', 'note_signed',
  'routing_attempt_failed', 'physician_status_changed', 'camera_active', 'camera_inactive', 'agent_heartbeat_lost', 'shift_started']

function InjectEvent({ hospitals, physicians, asOf }: { hospitals: Any[]; physicians: Any[]; asOf?: string }) {
  const { actor } = useRole()
  const { run, busy } = useAction()
  const plus = (m: number) => {
    // Scenario time + m minutes, written in the scenario's own UTC offset (e.g. 2026-03-17T18:21:00-04:00).
    if (!asOf) return ''
    const off = asOf.slice(19)
    const sign = off.startsWith('-') ? -1 : 1
    const offMin = sign * (Number(off.slice(1, 3)) * 60 + Number(off.slice(4, 6)))
    const d = new Date(new Date(asOf).getTime() + (m + offMin) * 60000)
    return d.toISOString().slice(0, 16) + ':00' + off
  }
  const [ev, setEv] = useState<Any>({ event_type: 'consult_received', consult_id: '', hospital_id: '', physician_id: '', description: 'Stroke consult request received', event_time: '' })
  const set = (k: string, v: string) => setEv({ ...ev, [k]: v })
  return (
    <Panel title={<span className="flex items-center gap-2"><Zap className="h-4 w-4 text-warn" />Add a single live event</span>} subtitle="For the live test: the state, detections, projection and recommendations recompute immediately.">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Event type<Select className="mt-1 block w-full" label="Event type" value={ev.event_type} onChange={(v) => set('event_type', v)}>{EVENT_TYPES.map((x) => <option key={x}>{x}</option>)}</Select></label>
        <label className="text-sm">Event time (with offset)
          <div className="mt-1 flex gap-1">
            <input value={ev.event_time} onChange={(e) => set('event_time', e.target.value)} placeholder={plus(1)} className="min-w-0 flex-1 rounded-lg border border-line px-2.5 py-1.5 text-sm" />
            <Button size="sm" variant="secondary" onClick={() => set('event_time', plus(1))}>Now +1m</Button>
          </div></label>
        <label className="text-sm">Hospital<Select className="mt-1 block w-full" label="Hospital" value={ev.hospital_id} onChange={(v) => set('hospital_id', v)}><option value="">—</option>{hospitals.map((h) => <option key={h.hospital_id} value={h.hospital_id}>{h.hospital_name}</option>)}</Select></label>
        <label className="text-sm">Physician<Select className="mt-1 block w-full" label="Physician" value={ev.physician_id} onChange={(v) => set('physician_id', v)}><option value="">—</option>{physicians.map((p) => <option key={p.physician_id} value={p.physician_id}>{p.name}</option>)}</Select></label>
        <label className="text-sm">Consult ID<input value={ev.consult_id} onChange={(e) => set('consult_id', e.target.value)} placeholder="e.g. CON-2201" className="mt-1 block w-full rounded-lg border border-line px-2.5 py-1.5 text-sm" /></label>
        <label className="text-sm">Description<input value={ev.description} onChange={(e) => set('description', e.target.value)} className="mt-1 block w-full rounded-lg border border-line px-2.5 py-1.5 text-sm" /></label>
      </div>
      <p className="mt-2 text-xs text-ink-soft">For a new consult, the description sets its type: "Stroke consult request received" or "General Neuro consult request received". Status events use "Self-reported status: Available".</p>
      <div className="mt-3 flex justify-end">
        <Button busy={busy === 'inj'} disabled={!ev.event_type} onClick={() => run('inj', () => api.post('/api/events', { ...ev, event_time: ev.event_time || plus(1), actor }), (r) => `${r.event_id} added`)}>Add event</Button>
      </div>
    </Panel>
  )
}
