export type Role = 'admin' | 'user'
export type AttendanceStatus = 'pending' | 'approved' | 'rejected'

export type Frequency = 'daily' | 'weekly' | 'monthly'

export interface GroupBrief {
  id: number
  name: string
}

export interface Group extends GroupBrief {
  description: string
  created_at: string
  member_ids: number[]
}

export interface User {
  id: number
  email: string
  full_name: string
  role: Role
  is_active: boolean
  created_at: string
  groups: GroupBrief[]
}

export interface Series {
  id: number
  frequency: Frequency
  interval: number
  weekdays: string
  until: string | null
  count: number | null
  timezone: string
}

export interface EventItem {
  id: number
  title: string
  description: string
  location: string
  starts_at: string
  ends_at: string
  check_in_opens_at: string
  check_in_closes_at: string
  late_after_minutes: number
  created_at: string
  series_id: number | null
  series: Series | null
  groups: GroupBrief[]
  check_in_open: boolean
  my_attendance_status: AttendanceStatus | null
}

export interface Attendance {
  id: number
  event_id: number
  user_id: number
  activity_summary: string
  location_note: string
  declaration: boolean
  is_late: boolean
  status: AttendanceStatus
  review_comment: string
  reviewed_at: string | null
  submitted_at: string
  source: 'self' | 'ocr'
  user: { id: number; email: string; full_name: string }
  event: { id: number; title: string; starts_at: string }
}

export type OcrStatus = 'matched' | 'review' | 'unmatched' | 'duplicate' | 'already_present' | 'ignored'

export interface OcrLine {
  index: number
  image_index: number
  raw: string
  normalized: string
  status: OcrStatus
  user_id: number | null
  score: number
  in_audience: boolean
  suggestions: { user_id: number; full_name: string; score: number }[]
}

export interface OcrImport {
  id: number
  event_id: number | null
  engine: string
  image_count: number
  created_at: string
  committed_at: string | null
  detected_date: string | null
  date_text: string
  photo_date: string | null
  event: EventItem | null
  suggested_events: EventItem[]
  lines: OcrLine[]
  created_attendances: number
}

export interface OcrImportBrief {
  id: number
  event_id: number | null
  event_title: string | null
  engine: string
  image_count: number
  line_count: number
  created_at: string
  committed_at: string | null
  created_attendances: number
}

export interface AttendanceSummary {
  total: number
  late: number
  by_status: Partial<Record<AttendanceStatus, number>>
  by_source: Partial<Record<'self' | 'ocr', number>>
  per_event: {
    event_id: number
    title: string
    starts_at: string
    count: number
    approved: number
    from_lists: number
    expected: number
  }[]
  per_group: { group: string; count: number }[]
  top_users: { user_id: number; full_name: string; count: number }[]
  granularity: Granularity
  trend: { period: string; self: number; ocr: number; late: number }[]
  by_weekday: number[]
  events_in_scope: number
  students_in_scope: number
  avg_turnout: number | null
  at_risk: number
  students_low: StudentRate[]
  students_high: StudentRate[]
  group_rates: { group_id: number; group: string; attended: number; expected: number; rate: number }[]
}

export type Granularity = 'day' | 'week' | 'month'

export interface StudentRate {
  user_id: number
  full_name: string
  attended: number
  expected: number
  rate: number
}

export const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

export interface AttendancePage {
  items: Attendance[]
  total: number
  page: number
  page_size: number
}

export interface Stats {
  total_users: number
  total_events: number
  total_attendances: number
  pending: number
  approved: number
  rejected: number
  late: number
  upcoming_events: number
  recent_events: {
    id: number
    title: string
    starts_at: string
    attendances: number
    expected: number
    groups: string[]
  }[]
}

const TOKEN_KEY = 'attendance.token'

export const tokenStore = {
  get: (): string | null => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set: (t: string | null) => {
    try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
  },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn }

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown })?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg ?? String(d)).join('; ')
  return fallback
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const apiOrigin = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')
  if (apiOrigin) headers.set('ngrok-skip-browser-warning', 'true')
  const res = await fetch(`${apiOrigin}/api${path}`, { ...init, headers })
  if (!res.ok) {
    if (res.status === 401 && token) onUnauthorized()
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, errorMessage(body, res.statusText))
  }
  return res
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await raw(path, init)
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function fetchBlob(path: string): Promise<{ blob: Blob; filename: string | null }> {
  const res = await raw(path)
  const cd = res.headers.get('Content-Disposition') ?? ''
  const filename = /filename="?([^";]+)"?/.exec(cd)?.[1] ?? null
  return { blob: await res.blob(), filename }
}

export async function download(path: string, fallbackName: string) {
  const { blob, filename } = await fetchBlob(path)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename ?? fallbackName
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function describeSeries(s: Series): string {
  const every = s.interval === 1 ? '' : ` ${s.interval}`
  const unit = { daily: 'day', weekly: 'week', monthly: 'month' }[s.frequency] + (s.interval === 1 ? '' : 's')
  const days = s.frequency === 'weekly' && s.weekdays
    ? ` on ${s.weekdays.split(',').map((d) => WEEKDAYS[Number(d)]).join(', ')}`
    : ''
  const end = s.until ? `, until ${s.until}` : s.count ? `, ${s.count} times` : ''
  return `Every${every} ${unit}${days}${end}`
}

export const fmt = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—'
