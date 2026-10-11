// Thin API client. All important actions go through the FastAPI backend and are persisted there.
/* eslint-disable @typescript-eslint/no-explicit-any */
export type Any = any

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export class ApiFailure extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Demo sign-in token. sessionStorage keeps each browser tab signed in separately, so one tab can be the
 * coordinator and another the clinical lead during a demo. */
const KEY = 'sevaro.token'
export const tokenStore = {
  get: (): string | null => { try { return sessionStorage.getItem(KEY) } catch { return null } },
  set: (t: string | null) => { try { if (t) sessionStorage.setItem(KEY, t); else sessionStorage.removeItem(KEY) } catch { /* storage blocked */ } },
}
const authHeaders = (): Record<string, string> => { const t = tokenStore.get(); return t ? { Authorization: `Bearer ${t}` } : {} }

async function handle(r: Response) {
  if (r.status === 401 && !r.url.endsWith('/api/auth/login')) window.dispatchEvent(new Event('sevaro:signed-out'))
  const text = await r.text()
  let body: Any = null
  try { body = text ? JSON.parse(text) : null } catch { body = text }
  if (!r.ok) {
    const msg = body?.error ?? (Array.isArray(body?.detail) ? body.detail.map((d: Any) => d.msg).join('; ') : body?.detail) ?? `Request failed (${r.status})`
    throw new ApiFailure(r.status, msg)
  }
  return body
}

export const api = {
  get: (path: string) => fetch(BASE + path, { headers: authHeaders() }).then(handle),
  post: (path: string, data?: unknown) =>
    fetch(BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(data ?? {}) }).then(handle),
  put: (path: string, data?: unknown) =>
    fetch(BASE + path, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(data ?? {}) }).then(handle),
  del: (path: string) => fetch(BASE + path, { method: 'DELETE', headers: authHeaders() }).then(handle),
  upload: (path: string, form: FormData) => fetch(BASE + path, { method: 'POST', body: form, headers: authHeaders() }).then(handle),
  /** For plain links (downloads): fetch with the token and save the result. */
  download: async (path: string, filename: string) => {
    const r = await fetch(BASE + path, { headers: authHeaders() })
    const url = URL.createObjectURL(await r.blob())
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url)
  },
  url: (path: string) => BASE + path,
}

export const t = (iso?: string | null) => (iso ? iso.slice(11, 16) : '—')
export const tSec = (iso?: string | null) => (iso ? iso.slice(11, 19) : '—')
export const wall = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'
export const wallDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
