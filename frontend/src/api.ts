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

async function handle(r: Response) {
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
  get: (path: string) => fetch(BASE + path).then(handle),
  post: (path: string, data?: unknown) =>
    fetch(BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data ?? {}) }).then(handle),
  put: (path: string, data?: unknown) =>
    fetch(BASE + path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data ?? {}) }).then(handle),
  del: (path: string) => fetch(BASE + path, { method: 'DELETE' }).then(handle),
  upload: (path: string, form: FormData) => fetch(BASE + path, { method: 'POST', body: form }).then(handle),
  url: (path: string) => BASE + path,
}

export const t = (iso?: string | null) => (iso ? iso.slice(11, 16) : '—')
export const tSec = (iso?: string | null) => (iso ? iso.slice(11, 19) : '—')
export const wall = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'
export const wallDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
