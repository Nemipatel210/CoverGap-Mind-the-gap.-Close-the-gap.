import { useState } from 'react'
import { Link } from 'react-router-dom'
import { type Any, t } from '../api'
import { ErrorNote, Loading, usePoll } from '../ui'
import { Runway } from '../components/Runway'

/** Look-ahead: which hospitals will be short, and when. */
export default function Coverage() {
  const { data, error } = usePoll<Any>('/api/coverage', 5000)
  const phys = usePoll<Any>('/api/physicians', 8000)
  const [all, setAll] = useState(false)
  if (error && !data) return <ErrorNote text={error} />
  if (!data) return <Loading />
  const A = data.assumptions
  const incFor = (hid: string) => data.incidents.find((i: Any) => i.hospitals.includes(hid))

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-2xl font-semibold tracking-tight text-navy">Coverage, next {A.horizon_min / 60} hours</h1>
      <p className="mt-1 max-w-3xl text-sm text-ink-soft">Approved doctors available at each hospital against the minimum it needs, every {A.step_min} minutes. Shift ends are marked where they land. A surge adds one to the minimum.</p>

      {(data.routing_gaps.length > 0 || data.roster_gaps.length > 0) && (
        <ul className="mt-5 space-y-2">
          {data.routing_gaps.filter((g: Any) => g.remaining > 0).map((g: Any) => (
            <li key={g.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-bad/30 bg-white px-4 py-3 text-sm">
              <span className="font-semibold text-navy">{g.hospital_name}</span>
              <span>nobody approved is free now; {g.waiting_consults.join(', ')} waiting{g.pending_joiners.length > 0 && `. ${g.pending_joiners[0].name} joins at ${t(g.pending_joiners[0].online_at)}, still short ${g.remaining}`}</span>
              {incFor(g.hospital_id) && <Link className="ml-auto font-medium text-teal-600" to={`/decide/${encodeURIComponent(incFor(g.hospital_id).id)}`}>Plan cover</Link>}
            </li>
          ))}
          {data.roster_gaps.map((g: Any) => (
            <li key={g.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-warn/40 bg-white px-4 py-3 text-sm">
              <span className="font-semibold text-navy">{g.hospital_name}</span>
              <span className="num">{g.available} of {g.required} doctors from {t(g.start)} to {t(g.end)}</span>
              {incFor(g.hospital_id) && <Link className="ml-auto font-medium text-teal-600" to={`/decide/${encodeURIComponent(incFor(g.hospital_id).id)}`}>Plan cover</Link>}
            </li>
          ))}
        </ul>
      )}

      <section className="mt-5 rounded-xl border border-line bg-white p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-navy">{all ? 'All hospitals' : 'Hospitals short or at their minimum'}</h2>
          <button className="text-sm font-medium text-teal-600" onClick={() => setAll(!all)}>{all ? 'Show only hospitals at risk' : 'Show all hospitals'}</button>
        </div>
        <Runway coverage={data.coverage} physicians={phys.data?.on_shift} onlyAttention={!all} />
      </section>
      <p className="mt-3 text-xs text-ink-soft">Counts doctors on shift and approved there who aren't Temporarily Unavailable{A.count_scheduled_starts ? ', doctors whose scheduled shift has started' : ''}, and accepted extra shifts. Busy doctors still count here; the "nobody free" warnings above cover that.</p>
    </div>
  )
}
