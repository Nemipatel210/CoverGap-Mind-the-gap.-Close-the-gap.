import { useState } from 'react'
import Physicians from './Physicians'
import Consults from './Consults'

/** Reference view: what each doctor is doing and where each consult is, kept separate. */
export default function Details() {
  const [tab, setTab] = useState<'doctors' | 'consults'>('doctors')
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-navy">Doctors & consults</h1>
      <p className="mt-1 text-sm text-ink-soft">What each doctor is doing, worked out from their signals, and where each consult is against its time limit. Tracked separately.</p>
      <div role="tablist" className="my-5 inline-flex rounded-lg border border-line bg-white p-1">
        {(['doctors', 'consults'] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium ${tab === k ? 'bg-teal text-white' : 'text-ink-soft hover:text-ink'}`}>
            {k === 'doctors' ? 'Doctors' : 'Consults'}
          </button>
        ))}
      </div>
      {tab === 'doctors' ? <Physicians embedded /> : <Consults embedded />}
    </div>
  )
}
