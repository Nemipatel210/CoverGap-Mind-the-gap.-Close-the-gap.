import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, ShieldCheck } from 'lucide-react'
import { type Any, t } from '../api'
import { Badge, Empty, ErrorNote, Loading, usePoll } from '../ui'
import { FixAction, HandoffList, ProblemRow, Where, sevDot } from '../components/Problem'

/** Coordinator home: the one thing to act on first, then the rest in order. */
export default function CommandCenter() {
  const { data, error } = usePoll<Any>('/api/problems', 4000)
  const [showLow, setShowLow] = useState(false)
  const [more, setMore] = useState(false)
  if (error && !data) return <ErrorNote text={error} />
  if (!data) return <Loading />
  const all: Any[] = data.problems
  const first = all.find((p) => !p.status && !['monitor', 'covered'].includes(p.fix.kind)) ?? all[0]
  const rest = all.filter((p) => p !== first)
  const main = rest.filter((p) => p.severity !== 'info' && !['monitor', 'covered'].includes(p.fix.kind))
  const low = rest.filter((p) => !main.includes(p))
  const s = data.summary

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight text-navy">What to do now</h1>
        <p className="mt-1 text-sm text-ink-soft">
          {s.stroke_waiting > 0 && <><span className="font-medium text-bad">{s.stroke_waiting} stroke patient{s.stroke_waiting > 1 ? 's' : ''} waiting</span> · </>}
          {s.short_now} hospital{s.short_now === 1 ? '' : 's'} with nobody free · {s.short_soon} short within 2 hours
          {s.awaiting_approval > 0 && <> · {s.awaiting_approval} offer{s.awaiting_approval > 1 ? 's' : ''} waiting for approval</>}
        </p>
      </div>

      {!first ? <Empty>Nothing needs attention right now.</Empty> : (
        <section aria-label="Act on this first" className="rounded-2xl border-2 border-navy/80 bg-white">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-2.5">
            <span className="text-sm font-semibold text-navy">Act on this first</span>
            <span className={`h-2.5 w-2.5 rounded-full ${sevDot(first.severity)}`} />
            <span className="text-xs text-ink-soft">{first.severity === 'critical' ? 'Critical' : 'Warning'}{first.stroke ? ' · stroke' : ''}</span>
          </div>
          <div className="px-5 py-5">
            <p className="text-xs font-medium text-ink-soft">What is going on</p>
            <h2 className="mt-0.5 text-xl font-semibold leading-snug text-ink">{first.what}</h2>
            <p className="mt-1"><span className="text-xs font-medium text-ink-soft">Where </span><Where w={first.where} /></p>
            <div className="mt-5 grid gap-6 md:grid-cols-2">
              <div>
                <p className="mb-1.5 text-xs font-medium text-ink-soft">Why it matters</p>
                <ul className="space-y-1.5 text-sm">
                  {first.matters.map((m: string, i: number) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-faint" />{m}</li>)}
                </ul>
              </div>
              <div className="rounded-xl bg-teal-50 p-4">
                <p className="mb-1.5 text-xs font-medium text-teal-600">What to do</p>
                <p className="text-sm">{first.fix.why}</p>
                {first.fix.approver !== '—' && <p className="mt-2 flex items-center gap-1.5 text-xs text-ink-soft"><ShieldCheck className="h-3.5 w-3.5" />Approved by: {first.fix.approver}</p>}
                <div className="mt-4"><FixAction p={first} size="lg" /></div>
                <div className="mt-2"><HandoffList p={first} /></div>
                {first.alternatives.length > 0 && <p className="mt-3 text-xs text-ink-soft">Other options: {first.alternatives.join(' ')}</p>}
              </div>
            </div>
          </div>
        </section>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
        <section>
          <h2 className="mb-2 text-sm font-semibold text-navy">Then, in order ({main.length})</h2>
          {main.length === 0 ? <Empty>Nothing else needs action.</Empty> : (
            <>
              <ol className="overflow-hidden rounded-xl border border-line bg-white">{(more ? main : main.slice(0, 6)).map((p) => <ProblemRow key={p.id} p={p} />)}</ol>
              {main.length > 6 && <button className="mt-2 text-sm font-medium text-teal-600" onClick={() => setMore(!more)}>{more ? 'Show fewer' : `Show ${main.length - 6} more`}</button>}
            </>
          )}
          {low.length > 0 && (
            <div className="mt-3">
              <button className="block text-sm font-medium text-teal-600" onClick={() => setShowLow(!showLow)} aria-expanded={showLow}>
                {showLow ? 'Hide' : 'Show'} {low.length} item{low.length > 1 ? 's' : ''} to watch (no action needed)
              </button>
              {showLow && <ol className="mt-2 overflow-hidden rounded-xl border border-line bg-white">{low.map((p) => <ProblemRow key={p.id} p={p} />)}</ol>}
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-xl border border-line bg-white p-4">
            <h2 className="text-sm font-semibold text-navy">Next 2 hours</h2>
            {data.next90.length === 0 ? <p className="mt-2 text-sm text-ink-soft">Every hospital stays covered.</p> : (
              <ul className="mt-2 space-y-2 text-sm">
                {data.next90.map((n: Any) => (
                  <li key={n.hospital_id} className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0">{n.hospital}</span>
                    <Badge tone={n.short ? 'critical' : 'warning'} className="num shrink-0">{n.available}/{n.required} at {t(n.at)}</Badge>
                  </li>
                ))}
              </ul>
            )}
            <Link to="/coverage" className="mt-3 inline-block text-xs font-medium text-teal-600">See the coverage timeline</Link>
          </section>
          <section className="rounded-xl border border-line bg-white p-4 text-sm">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-navy"><CheckCircle2 className="h-4 w-4 text-ok" />Data checked</h2>
            <p className="mt-1 text-ink-soft">{data.data.events.toLocaleString()} events replayed in the order they happened. {data.data.late} late and {data.data.duplicates} duplicate record{data.data.duplicates === 1 ? '' : 's'} corrected.</p>
            <Link to="/details" className="mt-2 inline-block text-xs font-medium text-teal-600">Doctors & consults</Link>
          </section>
        </aside>
      </div>
    </div>
  )
}
