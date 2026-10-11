import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from 'lucide-react'
import { api, type Any } from './api'

/* ------------------------------------------------------------------ polling --- */
export function usePoll<T = Any>(path: string | null, ms = 4000) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const alive = useRef(true)
  const load = useCallback(async () => {
    if (!path) return
    try {
      const d = await api.get(path)
      if (alive.current) { setData(d); setError(null) }
    } catch (e) {
      if (alive.current) setError((e as Error).message)
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [path])
  useEffect(() => {
    alive.current = true
    setLoading(true)
    load()
    const id = setInterval(load, ms)
    const onChange = () => load()
    window.addEventListener('sevaro:changed', onChange)
    return () => { alive.current = false; clearInterval(id); window.removeEventListener('sevaro:changed', onChange) }
  }, [load, ms])
  return { data, error, loading, reload: load }
}

/** Tell every polling view to refresh right away after a mutation. */
export const announceChange = () => window.dispatchEvent(new Event('sevaro:changed'))

/* ------------------------------------------------------------------- toasts --- */
type Toast = { id: number; kind: 'success' | 'error' | 'info'; text: string }
const ToastCtx = createContext<(kind: Toast['kind'], text: string) => void>(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((kind: Toast['kind'], text: string) => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, kind, text }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), kind === 'error' ? 7000 : 4000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2" role="status" aria-live="polite">
        {items.map((i) => (
          <div key={i.id} className={`flex items-start gap-2 rounded-lg border bg-white px-3 py-2.5 text-sm shadow-lg ${
            i.kind === 'error' ? 'border-bad/40' : i.kind === 'success' ? 'border-ok/40' : 'border-line'}`}>
            {i.kind === 'error' ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-bad" /> :
              i.kind === 'success' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" /> :
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-teal" />}
            <span className="flex-1">{i.text}</span>
            <button aria-label="Dismiss" onClick={() => setItems((x) => x.filter((y) => y.id !== i.id))}><X className="h-4 w-4 text-ink-faint" /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

/** Run an action with toast feedback and a global refresh. */
export function useAction() {
  const toast = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  const run = useCallback(async (key: string, fn: () => Promise<Any>, ok?: string | ((r: Any) => string)) => {
    setBusy(key)
    try {
      const r = await fn()
      if (ok) toast('success', typeof ok === 'function' ? ok(r) : ok)
      announceChange()
      return r
    } catch (e) {
      toast('error', (e as Error).message)
      return null
    } finally {
      setBusy(null)
    }
  }, [toast])
  return { run, busy }
}

/* --------------------------------------------------------------- primitives --- */
type Tone = 'critical' | 'warning' | 'info' | 'ok' | 'neutral' | 'teal'
const toneCls: Record<Tone, string> = {
  critical: 'bg-bad-50 text-bad border-bad/25',
  warning: 'bg-warn-50 text-warn border-warn/25',
  info: 'bg-navy-100 text-navy-600 border-navy-600/15',
  ok: 'bg-ok-50 text-ok border-ok/25',
  neutral: 'bg-canvas text-ink-soft border-line',
  teal: 'bg-teal-50 text-teal-600 border-teal/25',
}
export function Badge({ tone = 'neutral', children, className = '' }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-xs font-medium ${toneCls[tone]} ${className}`}>{children}</span>
}

export const sevTone = (s?: string): Tone =>
  s === 'critical' ? 'critical' : s === 'warning' ? 'warning' : s === 'ok' ? 'ok' : 'info'

export const statusTone = (s: string): Tone =>
  ({ proposed: 'warning', sent: 'warning', accepted: 'ok', authorized: 'ok', declined: 'critical', rejected: 'critical',
     timed_out: 'critical', not_needed: 'neutral', withdrawn: 'neutral', pending: 'warning' } as Record<string, Tone>)[s] ?? 'neutral'

export const statusLabel = (s: string) =>
  ({ proposed: 'Awaiting approval', sent: 'Sent · awaiting reply', accepted: 'Accepted', declined: 'Declined',
     rejected: 'Rejected by lead', timed_out: 'Timed out', not_needed: 'Not needed (already filled)',
     withdrawn: 'Withdrawn', pending: 'Pending', authorized: 'Authorized' } as Record<string, string>)[s] ?? s

export function Button({ children, onClick, variant = 'primary', busy, disabled, size = 'md', className = '', type = 'button', title }: {
  children: ReactNode; onClick?: () => void; variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
  busy?: boolean; disabled?: boolean; size?: 'sm' | 'md' | 'lg'; className?: string; type?: 'button' | 'submit'; title?: string
}) {
  const v = {
    primary: 'bg-navy text-white hover:bg-navy-700 border-navy',
    secondary: 'bg-white text-ink border-line hover:border-ink-faint',
    ghost: 'bg-transparent text-teal-600 border-transparent hover:bg-teal-50',
    danger: 'bg-white text-bad border-bad/40 hover:bg-bad-50',
    success: 'bg-ok text-white border-ok hover:brightness-95',
  }[variant]
  const s = { sm: 'px-2.5 py-1 text-xs', md: 'px-3.5 py-2 text-sm', lg: 'px-5 py-3.5 text-base' }[size]
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${v} ${s} ${className}`}>
      {busy && <Loader2 className="h-4 w-4 animate-spin" />}{children}
    </button>
  )
}

export function Panel({ title, action, children, className = '', pad = true, subtitle }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean; subtitle?: ReactNode
}) {
  return (
    <section className={`rounded-xl border border-line bg-white ${className}`}>
      {(title || action) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-[15px] font-semibold text-navy">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-ink-soft">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={pad ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

export function PageHeader({ title, children, lede }: { title: string; children?: ReactNode; lede?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-navy">{title}</h1>
        {lede && <p className="mt-1 text-sm text-ink-soft">{lede}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return <div className="flex items-center gap-2 p-6 text-sm text-ink-soft"><Loader2 className="h-4 w-4 animate-spin" />{label}…</div>
}

export function ErrorNote({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-bad/30 bg-bad-50 p-3 text-sm text-bad">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div><p className="font-medium">Can't reach the command center API.</p><p className="text-bad/80">{text}. Start the backend with <code>uvicorn main:app --reload</code> in /backend.</p></div>
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-ink-soft">{children}</div>
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    if (open) window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-navy/40 p-0 sm:items-center sm:p-6" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
        className={`max-h-[92vh] w-full overflow-auto rounded-t-2xl bg-white shadow-xl sm:rounded-2xl ${wide ? 'sm:max-w-4xl' : 'sm:max-w-lg'}`}>
        <div className="sticky top-0 flex items-center justify-between border-b border-line bg-white px-5 py-3">
          <h3 className="font-semibold text-navy">{title}</h3>
          <button aria-label="Close" onClick={onClose}><X className="h-5 w-5 text-ink-faint" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

export function Stat({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: Tone; hint?: string }) {
  const c = tone === 'critical' ? 'text-bad' : tone === 'warning' ? 'text-warn' : tone === 'ok' ? 'text-ok' : 'text-navy'
  return (
    <div className="min-w-0 px-4 py-3" title={hint}>
      <div className={`num text-2xl font-semibold leading-tight ${c}`}>{value}</div>
      <div className="mt-0.5 truncate text-xs text-ink-soft">{label}</div>
    </div>
  )
}

export function Select({ value, onChange, children, className = '', label }: { value: string; onChange: (v: string) => void; children: ReactNode; className?: string; label?: string }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
      className={`rounded-lg border border-line bg-white px-2.5 py-1.5 text-sm ${className}`}>{children}</select>
  )
}
