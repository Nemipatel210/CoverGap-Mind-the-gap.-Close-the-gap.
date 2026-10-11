/* Browsers only allow sound after the user has tapped the page. We create one AudioContext and unlock it on the
 * first tap (signing in counts), so a call arriving later can ring. If the page was reloaded without a tap, the
 * phone view shows a "Tap to turn on call sound" bar. */
type Ctx = AudioContext
let ctx: Ctx | null = null
const listeners = new Set<() => void>()

function get(): Ctx | null {
  if (ctx) return ctx
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    ctx = AC ? new AC() : null
    ctx?.addEventListener?.('statechange', () => listeners.forEach((f) => f()))
  } catch { ctx = null }
  return ctx
}

export function unlockAudio() {
  const c = get()
  if (!c) return
  if (c.state !== 'running') c.resume().catch(() => {})
  try { // a silent blip finishes the unlock on iOS
    const b = c.createBuffer(1, 1, 22050), s = c.createBufferSource()
    s.buffer = b; s.connect(c.destination); s.start(0)
  } catch { /* ignore */ }
  listeners.forEach((f) => f())
}

export function installAudioUnlock() {
  const h = () => unlockAudio()
  ;['pointerdown', 'touchend', 'keydown'].forEach((e) => window.addEventListener(e, h, { passive: true }))
  return () => ['pointerdown', 'touchend', 'keydown'].forEach((e) => window.removeEventListener(e, h))
}

export const audioReady = () => get()?.state === 'running'
export function onAudioChange(f: () => void) { listeners.add(f); return () => { listeners.delete(f) } }

/** One ring: two-tone (440 + 480 Hz) like a phone, about 1 second. */
export function ringOnce() {
  try { navigator.vibrate?.([500, 250, 500]) } catch { /* no vibration */ }
  const c = get()
  if (!c || c.state !== 'running') return false
  const t0 = c.currentTime
  for (const [start, len] of [[0, 0.45], [0.6, 0.45]]) {
    const g = c.createGain()
    g.connect(c.destination)
    g.gain.setValueAtTime(0.0001, t0 + start)
    g.gain.exponentialRampToValueAtTime(0.35, t0 + start + 0.03)
    g.gain.setValueAtTime(0.35, t0 + start + len - 0.05)
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + start + len)
    for (const f of [440, 480]) {
      const o = c.createOscillator()
      o.type = 'sine'; o.frequency.value = f
      o.connect(g); o.start(t0 + start); o.stop(t0 + start + len + 0.02)
    }
  }
  return true
}
