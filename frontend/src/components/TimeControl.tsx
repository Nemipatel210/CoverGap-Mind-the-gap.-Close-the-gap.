import { useEffect, useRef, useState } from 'react'
import { Clock, Pause, Play, RotateCcw } from 'lucide-react'
import { api, type Any, t } from '../api'
import { announceChange, useToast } from '../ui'

const STEPS = [-15, -5, 1, 5, 15, 60]

/** Demo time control: move the scenario clock and watch the engine produce (and clear) alerts. */
export function TimeControl({ clock, label, canEdit }: { clock: Any; label?: string; canEdit: boolean }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jump, setJump] = useState('')
  const [last, setLast] = useState<Any>(null)
  const toast = useToast()
  const box = useRef<HTMLDivElement>(null)
  const sim = clock?.mode === 'simulated'
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const send = async (body: Any) => {
    setBusy(true)
    try {
      const r = await api.post('/api/clock', body)
      setLast(r)
      const n = r.new_problems.length, w = r.worse_problems.length, g = r.resolved_problems.length
      if (body.action !== 'play' && body.action !== 'pause') {
        toast(n || w ? 'info' : 'success', `Now ${t(r.to)}. ${n} new problem${n === 1 ? '' : 's'}, ${w} got worse, ${g} resolved.`)
      }
      announceChange()
    } catch (e) {
      toast('error', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative min-w-0 flex-1" ref={box}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-w-0 max-w-full items-center gap-2 rounded-lg px-2 py-1 text-left hover:bg-canvas">
        <Clock className={`h-4 w-4 shrink-0 ${sim ? 'text-teal' : 'text-navy'}`} />
        <span className="min-w-0">
          <span className="num block truncate text-sm font-semibold text-navy">{label ?? '…'}</span>
          <span className="block truncate text-xs text-ink-soft">
            {sim ? <span className="font-medium text-teal-700">{clock.playing ? `Simulation running · +${clock.step_min} min every 5 s` : 'Simulated time'}</span> : 'Time of the latest event'}
          </span>
        </span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-40 mt-2 w-[min(92vw,380px)] rounded-xl border border-line bg-white p-4 shadow-xl">
          <div className="flex items-baseline justify-between">
            <p className="num text-2xl font-semibold text-navy">{t(clock?.as_of)}</p>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${sim ? 'bg-teal-50 text-teal-700' : 'bg-canvas text-ink-soft'}`}>{sim ? 'Simulated' : 'Data time'}</span>
          </div>
          <p className="mt-1 text-xs text-ink-soft">Move the clock to see how problems and alerts develop. Events after the chosen time are hidden; timers, shift changes and offer expiry follow the clock. Latest event: {t(clock?.data_now)}.</p>

          {canEdit ? (
            <>
              <div className="mt-3 grid grid-cols-6 gap-1">
                {STEPS.map((m) => (
                  <button key={m} disabled={busy} onClick={() => send({ action: 'advance', minutes: m })}
                    className={`num rounded-lg border px-1 py-2 text-sm font-medium disabled:opacity-50 ${m > 0 ? 'border-teal/40 text-teal-700 hover:bg-teal-50' : 'border-line text-ink-soft hover:bg-canvas'}`}>
                    {Math.abs(m) === 60 ? `${m > 0 ? '+' : '−'}1h` : `${m > 0 ? '+' : '−'}${Math.abs(m)}m`}
                  </button>
                ))}
              </div>
              <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (jump) send({ action: 'set', value: jump }) }}>
                <input type="time" value={jump} onChange={(e) => setJump(e.target.value)} aria-label="Jump to time"
                  className="num min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm" />
                <button disabled={!jump || busy} className="rounded-lg bg-teal px-3 py-2 text-sm font-medium text-white hover:bg-teal-600 disabled:opacity-50">Go</button>
              </form>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {['18:30', '18:59', '19:05', '20:05'].map((v) => (
                  <button key={v} disabled={busy} onClick={() => send({ action: 'set', value: v })} className="num rounded-full border border-line px-2.5 py-1 text-xs hover:border-teal hover:text-teal-700">{v}</button>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
                {clock?.playing ? (
                  <button onClick={() => send({ action: 'pause' })} className="inline-flex items-center gap-1.5 rounded-lg bg-navy px-3 py-2 text-sm font-medium text-white"><Pause className="h-4 w-4" />Pause</button>
                ) : (
                  <button onClick={() => send({ action: 'play', step_min: clock?.step_min ?? 1 })} className="inline-flex items-center gap-1.5 rounded-lg bg-teal px-3 py-2 text-sm font-medium text-white hover:bg-teal-600"><Play className="h-4 w-4" />Play</button>
                )}
                <select aria-label="Speed" value={clock?.step_min ?? 1} onChange={(e) => send({ action: clock?.playing ? 'play' : 'pause', step_min: Number(e.target.value) })}
                  className="rounded-lg border border-line px-2 py-2 text-sm">
                  {[1, 2, 5, 10].map((s) => <option key={s} value={s}>+{s} min / 5 s</option>)}
                </select>
                {sim && (
                  <button onClick={() => send({ action: 'live' })} className="ml-auto inline-flex items-center gap-1 text-sm text-ink-soft hover:text-navy"><RotateCcw className="h-3.5 w-3.5" />Back to data time</button>
                )}
              </div>
            </>
          ) : <p className="mt-3 text-sm text-ink-soft">Only the coordinator can move the clock.</p>}

          {last && (last.new_problems.length + last.worse_problems.length + last.resolved_problems.length) > 0 && (
            <div className="mt-4 border-t border-line pt-3 text-xs">
              <p className="font-semibold text-navy">What changed ({t(last.from)} → {t(last.to)})</p>
              <ul className="mt-1 max-h-48 space-y-1 overflow-auto">
                {last.new_problems.map((p: Any) => <li key={'n' + p.id}><span className="font-medium text-bad">New:</span> {p.what}</li>)}
                {last.worse_problems.map((p: Any) => <li key={'w' + p.id}><span className="font-medium text-warn">Worse:</span> {p.what}</li>)}
                {last.resolved_problems.map((p: Any) => <li key={'r' + p.id}><span className="font-medium text-ok">Resolved:</span> {p.what}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
