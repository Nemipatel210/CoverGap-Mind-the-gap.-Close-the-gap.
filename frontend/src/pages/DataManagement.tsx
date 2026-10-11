import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, FileUp, XCircle } from 'lucide-react'
import { api, type Any, t } from '../api'
import { useRole } from '../App'
import { Badge, Button, announceChange, useToast } from '../ui'
import FullDataset from '../components/FullDataset'

/** The live test: drop a file in event_stream.csv format; it is added to the day and the engine re-runs. */
export default function DataManagement() {
  const { actor } = useRole()
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<Any>(null)
  const [err, setErr] = useState<string | null>(null)

  const upload = async (files: FileList | File[]) => {
    const f = Array.from(files)[0]
    if (!f) return
    const fd = new FormData()
    fd.append('file', f)
    fd.append('actor', actor)
    setBusy(true); setErr(null); setRes(null)
    try {
      const r = await api.upload('/api/events/upload', fd)
      setRes(r)
      toast('success', `${r.new_events} new events added`)
      announceChange()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight text-navy">Add new events</h1>
      <p className="mt-1 text-sm text-ink-soft">Drop a file with the same 8 columns as event_stream.csv. It's added to the day, replayed in the order things happened, and the problems update. No restart.</p>

      <div onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}
        className={`mt-5 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center ${drag ? 'border-teal bg-teal-50' : 'border-line bg-white'}`}>
        <FileUp className="h-9 w-9 text-teal-600" />
        <p className="mt-3 font-medium">Drop the events file here</p>
        <p className="text-sm text-ink-soft">CSV or JSON</p>
        <Button className="mt-4" busy={busy} onClick={() => input.current?.click()}>Choose file</Button>
        <input ref={input} type="file" accept=".csv,.json,.txt" className="hidden" aria-label="Choose events file" onChange={(e) => e.target.files && upload(e.target.files)} />
      </div>

      {err && (
        <div className="mt-4 flex gap-2 rounded-xl border border-bad/30 bg-bad-50 p-4 text-sm text-bad">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div><p className="font-medium">Nothing was changed.</p><p>{err}</p></div>
        </div>
      )}

      {res && (
        <section className="mt-4 rounded-2xl border border-ok/40 bg-white p-5">
          <h2 className="flex items-center gap-2 font-semibold text-navy"><CheckCircle2 className="h-5 w-5 text-ok" />Added {res.new_events} new events</h2>
          <p className="num mt-1 text-sm">Clock moved from {t(res.clock_before)} to {t(res.clock_after)}.</p>
          <p className="mt-1 text-sm text-ink-soft">
            {res.already_known > 0 && `${res.already_known} already known and ignored. `}
            {res.duplicates_in_file > 0 && `${res.duplicates_in_file} duplicate${res.duplicates_in_file > 1 ? 's' : ''} in the file counted once. `}
            {res.late_events > 0 && `${res.late_events} arrived late and ${res.late_events > 1 ? 'were' : 'was'} placed at the time ${res.late_events > 1 ? 'they' : 'it'} happened. `}
            {res.skipped_rows > 0 && `${res.skipped_rows} malformed row${res.skipped_rows > 1 ? 's' : ''} skipped.`}
          </p>
          {[['New problems', res.new_problems, 'critical'], ['Got worse', res.worse_problems, 'warning'], ['Resolved', res.resolved_problems, 'ok']].map(([label, list, tone]) =>
            (list as Any[]).length > 0 && (
              <div key={label as string} className="mt-3">
                <p className="text-xs font-semibold text-navy">{label as string}</p>
                <ul className="mt-1 space-y-1 text-sm">
                  {(list as Any[]).map((p) => (
                    <li key={p.id} className="flex flex-wrap items-baseline gap-2">
                      <Badge tone={tone as Any}>{p.where.consult ?? p.where.hospital ?? p.where.doctor}</Badge>
                      <span>{p.what}</span>
                      {label !== 'Resolved' && <span className="text-ink-soft">→ {p.fix}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          {res.top_problem && (
            <div className="mt-4 rounded-xl bg-teal-50 p-3 text-sm">
              <span className="font-medium">Act on this first now: </span>{res.top_problem.what} ({res.top_problem.where.hospital}). {res.top_problem.fix}.
            </div>
          )}
          <Link to="/" className="mt-4 inline-flex rounded-lg bg-teal px-4 py-2 text-sm font-medium text-white hover:bg-teal-600">See what to do now</Link>
        </section>
      )}

      <details className="mt-10 rounded-xl border border-line bg-white">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-navy">More data options: replace the whole dataset, add one event by hand, reset the demo</summary>
        <div className="border-t border-line p-4"><FullDataset /></div>
      </details>
    </div>
  )
}
