import { useEffect, useRef, useState } from 'react'
import { Bot, Check, Mic, MicOff, Phone, PhoneOff, X } from 'lucide-react'
import { api, type Any, t } from '../api'
import { audioReady, onAudioChange, ringOnce, unlockAudio } from '../audio'

/* Browser speech: text-to-speech is widely supported; speech recognition only in some browsers (Chrome/Edge/Safari). */
const synth: SpeechSynthesis | null = typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Recognition: Any = typeof window !== 'undefined' ? (window as Any).SpeechRecognition || (window as Any).webkitSpeechRecognition : null

function say(text: string): Promise<void> {
  return new Promise((resolve) => {
    const estimate = 600 + text.length * 70
    if (!synth) { setTimeout(resolve, Math.min(4000, estimate)); return }
    let done = false
    const finish = () => { if (!done) { done = true; resolve() } }
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 1.02
    u.onend = finish
    u.onerror = finish
    // Some browsers never fire onend (e.g. right after cancel, or with no voices): never let the call hang.
    setTimeout(finish, estimate + 2500)
    synth.speak(u)
  })
}

const YES = /\b(yes|yeah|yep|yup|sure|accept|ok|okay|i can|i'll take it|sounds good)\b/i
const NO = /\b(no|nope|decline|can't|cannot|not tonight|not available|pass)\b/i

function useRingtone(on: boolean) {
  const [audible, setAudible] = useState(audioReady())
  useEffect(() => onAudioChange(() => setAudible(audioReady())), [])
  useEffect(() => {
    if (!on) return
    ringOnce()
    const id = setInterval(ringOnce, 2500)
    return () => clearInterval(id)
  }, [on, audible])
  return audible
}

/** Full-screen call on the doctor's phone. The assistant reads the approved offer and listens for yes or no. */
export function CallScreen({ offer, onDone }: { offer: Any; onDone: (result: Any) => void }) {
  const call = offer.call
  const [lines, setLines] = useState<{ who: string; text: string }[]>([])
  const [phase, setPhase] = useState<'ringing' | 'talking' | 'listening' | 'closing'>(call.status === 'in_progress' ? 'talking' : 'ringing')
  const [heard, setHeard] = useState('')
  const [busy, setBusy] = useState(false)
  const rec = useRef<Any>(null)
  const tries = useRef(0)
  const finished = useRef(false)
  const audible = useRingtone(phase === 'ringing')
  useEffect(() => () => { try { synth?.cancel(); rec.current?.abort() } catch { /* cleanup */ } }, [])

  const post = (body: Any) => api.post(`/api/offers/${offer.id}/call`, body).catch(() => null)

  const finish = async (action: 'accept' | 'decline') => {
    if (finished.current) return
    finished.current = true
    try { rec.current?.abort() } catch { /* not listening */ }
    synth?.cancel()
    setBusy(true); setPhase('closing')
    let r: Any = await api.post(`/api/offers/${offer.id}/respond`, { action, channel: 'ai_call' }).catch((e) => ({ error: (e as Error).message }))
    if (r?.error) {
      // The answer may have been saved even if the reply failed (e.g. a brief file lock): check before showing an error.
      const latest = await api.get('/api/offers').then((d: Any) => d.offers.find((o: Any) => o.id === offer.id)).catch(() => null)
      if (latest && ['accepted', 'declined', 'not_needed'].includes(latest.status)) r = latest
    }
    const closing = r?.error ? r.error : r.status === 'not_needed' ? 'Another doctor has already covered this shift. Thank you. Goodbye.'
      : action === 'accept' ? call.script.accepted : call.script.declined
    setLines((l) => [...l, { who: 'assistant', text: closing }])
    post({ action: 'assistant', text: closing })
    await say(closing)
    onDone(r)
  }

  const listen = () => {
    if (!Recognition || finished.current) { setPhase('listening'); return }
    const r = new Recognition()
    r.lang = 'en-US'; r.interimResults = true; r.maxAlternatives = 1
    rec.current = r
    setPhase('listening'); setHeard('')
    let final = ''
    r.onresult = (e: Any) => {
      const txt = Array.from(e.results).map((x: Any) => x[0].transcript).join(' ')
      setHeard(txt)
      if (e.results[e.results.length - 1].isFinal) final = txt
    }
    r.onerror = () => setPhase('listening')
    r.onend = async () => {
      if (finished.current || !final) return
      setLines((l) => [...l, { who: 'doctor', text: final }])
      post({ action: 'say', text: final })
      if (YES.test(final) && !NO.test(final)) return finish('accept')
      if (NO.test(final)) return finish('decline')
      if (tries.current++ < 2) {
        setLines((l) => [...l, { who: 'assistant', text: call.script.unclear }])
        setPhase('talking'); await say(call.script.unclear); listen()
      } else setPhase('listening')
    }
    try { r.start() } catch { setPhase('listening') }
  }

  const answer = () => {
    // Speech must start inside the tap, or phones block it; so speak first, then tell the server.
    unlockAudio()
    setPhase('talking')
    const talk = async () => {
      for (const line of call.script.intro) {
        if (finished.current) return
        setLines((l) => [...l, { who: 'assistant', text: line }])
        await say(line)
      }
      listen()
    }
    talk()
    post({ action: 'answer' })
  }

  const decline = async () => {
    finished.current = true
    await post({ action: 'miss' })
    onDone(null)
  }

  if (phase === 'ringing') {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-between bg-navy px-6 py-14 text-white">
        <div className="text-center">
          <p className="text-sm text-white/70">Incoming call</p>
          <div className="relative mx-auto mt-8 grid h-28 w-28 place-items-center">
            <span className="absolute inset-0 animate-ping rounded-full bg-teal/40 motion-reduce:animate-none" />
            <span className="relative grid h-24 w-24 place-items-center rounded-full bg-teal"><Bot className="h-11 w-11" /></span>
          </div>
          <p className="mt-6 text-2xl font-semibold">Sevaro coverage assistant</p>
          <p className="mt-1 text-sm text-white/70">AI-assisted call about your extra-shift request</p>
          <p className="num mt-4 text-sm text-white/80">{offer.hospital_names.join(', ')} · {t(offer.start)}–{t(offer.end)}</p>
          {!audible && (
            <button onClick={() => unlockAudio()} className="mt-6 rounded-full bg-white/15 px-4 py-2 text-sm font-medium">
              Tap to hear the ring
            </button>
          )}
        </div>
        <div className="flex w-full max-w-xs justify-between">
          <button onClick={decline} aria-label="Decline call" className="flex flex-col items-center gap-2 text-sm">
            <span className="grid h-16 w-16 place-items-center rounded-full bg-bad"><PhoneOff className="h-7 w-7" /></span>Not now
          </button>
          <button onClick={answer} aria-label="Answer call" className="flex flex-col items-center gap-2 text-sm">
            <span className="grid h-16 w-16 place-items-center rounded-full bg-ok"><Phone className="h-7 w-7" /></span>Answer
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-navy text-white">
      <div className="flex items-center gap-3 px-5 pb-4 pt-8">
        <span className="grid h-11 w-11 place-items-center rounded-full bg-teal"><Bot className="h-6 w-6" /></span>
        <div className="flex-1">
          <p className="font-semibold">Sevaro coverage assistant</p>
          <p className="text-xs text-white/60">AI-assisted call · simulated in this demo</p>
        </div>
      </div>
      <div className="flex-1 space-y-2 overflow-auto rounded-t-3xl bg-canvas px-4 py-5 text-ink">
        {lines.map((l, i) => (
          <p key={i} className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm ${l.who === 'assistant' ? 'bg-white' : 'ml-auto bg-teal text-white'}`}>{l.text}</p>
        ))}
        {phase === 'listening' && (
          <p className="flex items-center gap-2 px-1 pt-1 text-sm text-teal-700">
            {Recognition ? <><Mic className="h-4 w-4 animate-pulse motion-reduce:animate-none" />Listening… say “yes” or “no”{heard && <span className="text-ink-soft">: “{heard}”</span>}</>
              : <><MicOff className="h-4 w-4" />Voice reply isn't supported in this browser. Tap a button.</>}
          </p>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 bg-canvas px-4 pb-8 pt-2">
        <button disabled={busy} onClick={() => finish('decline')} className="inline-flex items-center justify-center gap-2 rounded-xl border border-line bg-white py-4 text-base font-medium text-ink disabled:opacity-50"><X className="h-5 w-5" />Decline</button>
        <button disabled={busy} onClick={() => finish('accept')} className="inline-flex items-center justify-center gap-2 rounded-xl bg-ok py-4 text-base font-medium text-white disabled:opacity-50"><Check className="h-5 w-5" />Accept</button>
      </div>
    </div>
  )
}
