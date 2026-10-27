import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  api, browserTz, describeSeries, download, fmt, json, qs, WEEKDAYS,
  type Attendance, type AttendancePage, type AttendanceStatus, type AttendanceSummary, type EventItem, type Granularity,
  type Group, type User,
} from '../../api'
import { ChartCard, Legend, LineChart, RateBars, ShareStrip, StackedColumns, type Series } from '../../charts'
import { AuthImage, ErrorNote, Modal, StatusBadge } from '../../components'

const FILTER_KEYS = [
  'event_id', 'series_id', 'user_id', 'group_id', 'status', 'is_late', 'source', 'q', 'date_from', 'date_to', 'sort',
] as const

/** yyyy-mm-dd in local time */
const localDay = (d: Date) => {
  const c = new Date(d)
  c.setMinutes(c.getMinutes() - c.getTimezoneOffset())
  return c.toISOString().slice(0, 10)
}
const daysAgo = (n: number) => localDay(new Date(Date.now() - n * 86400000))
const DATE_PRESETS: { label: string; from: () => string; to: () => string }[] = [
  { label: 'Last 7 days', from: () => daysAgo(6), to: () => localDay(new Date()) },
  { label: 'Last 30 days', from: () => daysAgo(29), to: () => localDay(new Date()) },
  { label: 'Last 90 days', from: () => daysAgo(89), to: () => localDay(new Date()) },
  {
    label: 'This month',
    from: () => localDay(new Date(new Date().getFullYear(), new Date().getMonth(), 1)),
    to: () => localDay(new Date()),
  },
  { label: 'All time', from: () => '', to: () => '' },
]
const PAGE_SIZE = 25

/** Day filters refer to the event's date, in the admin's local time (backend needs an offset). */
const dayBound = (v: string | null, end: boolean) =>
  v ? new Date(v.includes('T') ? v : `${v}T${end ? '23:59:59.999' : '00:00:00'}`).toISOString() : undefined

const SOURCE_SERIES: Series[] = [
  { key: 'self', label: 'Self check-in', color: 'var(--series-1)' },
  { key: 'ocr', label: 'Paper list', color: 'var(--series-2)' },
]
const pct = (n: number, total: number) => (total ? Math.round((n / total) * 100) : 0)
const shortDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

export default function Attendances() {
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState<AttendancePage | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [selected, setSelected] = useState<Attendance | null>(null)
  const [summary, setSummary] = useState<AttendanceSummary | null>(null)
  const [showCharts, setShowCharts] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const page = Number(params.get('page') ?? 1)
  const granularity = (params.get('by') ?? 'week') as Granularity

  const filters = Object.fromEntries(
    FILTER_KEYS.map((k) => [
      k, k.startsWith('date_') ? dayBound(params.get(k), k === 'date_to') : params.get(k) ?? undefined,
    ]),
  )
  const filterQs = qs(filters)
  const summaryQs = qs({ ...filters, sort: undefined, granularity, tz: browserTz() })

  const load = useCallback(() => {
    api<AttendancePage>(`/admin/attendances${filterQs}${filterQs ? '&' : '?'}page=${page}&page_size=${PAGE_SIZE}`)
      .then(setData)
      .catch((e) => setError(e.message))
  }, [filterQs, page])

  useEffect(load, [load])
  useEffect(() => {
    if (!showCharts) return
    let cancelled = false
    setRefreshing(true) // keep showing the previous charts, dimmed, instead of flashing empty
    api<AttendanceSummary>(`/admin/attendances/summary${summaryQs}`)
      .then((r) => { if (!cancelled) setSummary(r) }).catch(() => {})
      .finally(() => { if (!cancelled) setRefreshing(false) })
    return () => { cancelled = true }
  }, [summaryQs, showCharts, data])
  useEffect(() => {
    api<EventItem[]>('/events?scope=all').then(setEvents).catch(() => {})
    api<User[]>('/admin/users').then(setUsers).catch(() => {})
    api<Group[]>('/admin/groups').then(setGroups).catch(() => {})
  }, [])

  const setFilters = (values: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value); else next.delete(key)
    }
    if (!('page' in values)) next.delete('page')
    setParams(next)
  }
  const setFilter = (key: string, value: string) => setFilters({ [key]: value })

  // one entry per recurring series, named after its first occurrence
  const seriesOptions = [...new Map(
    events.filter((e) => e.series).sort((a, b) => a.starts_at.localeCompare(b.starts_at))
      .map((e) => [e.series_id, e] as const),
  ).values()]

  const activePreset = DATE_PRESETS.find((p) =>
    p.from() === (params.get('date_from') ?? '') && p.to() === (params.get('date_to') ?? ''))

  // human-readable chips for what is currently filtered, each removable
  const label: Record<string, (v: string) => string> = {
    event_id: (v) => `Event: ${events.find((e) => String(e.id) === v)?.title ?? v}`,
    series_id: (v) => `Series: ${seriesOptions.find((e) => String(e.series_id) === v)?.title ?? v}`,
    user_id: (v) => `Student: ${users.find((u) => String(u.id) === v)?.full_name ?? v}`,
    group_id: (v) => `Group: ${groups.find((g) => String(g.id) === v)?.name ?? v}`,
    status: (v) => `Status: ${v}`,
    is_late: (v) => (v === 'true' ? 'Late only' : 'On time only'),
    source: (v) => (v === 'ocr' ? 'Paper lists' : 'Self check-ins'),
    q: (v) => `“${v}”`,
    date_from: (v) => `From ${v}`,
    date_to: (v) => `To ${v}`,
  }
  const active = Object.keys(label).filter((k) => params.get(k))

  const exportAs = (format: 'csv' | 'xlsx') =>
    download(`/admin/attendances/export${qs({ ...filters, format })}`, `attendances.${format}`).catch((e) =>
      setError(e.message),
    )

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <>
      <div className="page-head">
        <h2>Attendances</h2>
        <div className="row">
          <Link className="button" to="/admin/import">⬆ Import paper list</Link>
          <button onClick={() => setShowCharts(!showCharts)}>{showCharts ? 'Hide charts' : 'Show charts'}</button>
          <button onClick={() => exportAs('csv')}>⬇ Export CSV</button>
          <button onClick={() => exportAs('xlsx')}>⬇ Export Excel</button>
        </div>
      </div>

      <div className="card filters">
        <input placeholder="Search name, email, event…" defaultValue={params.get('q') ?? ''}
          onKeyDown={(e) => e.key === 'Enter' && setFilter('q', e.currentTarget.value)}
          onBlur={(e) => setFilter('q', e.target.value)} />
        <select value={params.get('event_id') ?? ''} onChange={(e) => setFilter('event_id', e.target.value)}>
          <option value="">All events</option>
          {events.map((e) => <option key={e.id} value={e.id}>{e.title} ({fmt(e.starts_at)})</option>)}
        </select>
        {seriesOptions.length > 0 && (
          <select value={params.get('series_id') ?? ''} onChange={(e) => setFilter('series_id', e.target.value)}
            title="All occurrences of a recurring event">
            <option value="">All series</option>
            {seriesOptions.map((e) => (
              <option key={e.series_id} value={e.series_id ?? ''}>🔁 {e.title} ({describeSeries(e.series!)})</option>
            ))}
          </select>
        )}
        <select value={params.get('user_id') ?? ''} onChange={(e) => setFilter('user_id', e.target.value)}>
          <option value="">All users</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </select>
        <select value={params.get('group_id') ?? ''} onChange={(e) => setFilter('group_id', e.target.value)}>
          <option value="">All groups</option>
          {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
        <select value={params.get('status') ?? ''} onChange={(e) => setFilter('status', e.target.value)}>
          <option value="">Any status</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
        <select value={params.get('source') ?? ''} onChange={(e) => setFilter('source', e.target.value)}>
          <option value="">Any source</option>
          <option value="self">Self check-in</option>
          <option value="ocr">Paper list</option>
        </select>
        <select value={params.get('is_late') ?? ''} onChange={(e) => setFilter('is_late', e.target.value)}>
          <option value="">On time &amp; late</option>
          <option value="false">On time</option>
          <option value="true">Late</option>
        </select>
        <label className="inline" title="Date of the event">Events from
          <input type="date" value={(params.get('date_from') ?? '').slice(0, 10)}
            onChange={(e) => setFilter('date_from', e.target.value)} />
        </label>
        <label className="inline">to
          <input type="date" value={(params.get('date_to') ?? '').slice(0, 10)}
            onChange={(e) => setFilter('date_to', e.target.value)} />
        </label>
        <select value={params.get('sort') ?? '-submitted_at'} onChange={(e) => setFilter('sort', e.target.value)}>
          <option value="-submitted_at">Newest first</option>
          <option value="submitted_at">Oldest first</option>
          <option value="user">User A–Z</option>
          <option value="event">Event A–Z</option>
          <option value="status">Status</option>
        </select>
        <button className="link" onClick={() => setParams(new URLSearchParams())}>Clear</button>
        <div className="filter-presets">
          <div className="seg" role="group" aria-label="Event date range">
            {DATE_PRESETS.map((p) => (
              <button key={p.label} className={activePreset === p ? 'on' : ''}
                onClick={() => setFilters({ date_from: p.from(), date_to: p.to() })}>{p.label}</button>
            ))}
          </div>
          {showCharts && (
            <label className="inline small">Trend by
              <select value={granularity} onChange={(e) => setFilters({ by: e.target.value, page: String(page) })}>
                <option value="day">day</option>
                <option value="week">week</option>
                <option value="month">month</option>
              </select>
            </label>
          )}
        </div>
        {active.length > 0 && (
          <div className="chips active-filters">
            {active.map((k) => (
              <span key={k} className="chip on">
                {label[k](params.get(k)!)}
                <button className="link" aria-label={`Remove ${k}`} onClick={() => setFilter(k, '')}>✕</button>
              </span>
            ))}
          </div>
        )}
      </div>

      <ErrorNote error={error} />

      {showCharts && summary && (
        <Insights summary={summary} refreshing={refreshing} onFilter={setFilter} onFilters={setFilters} />
      )}

      <div className="card table-wrap">
        <table>
          <thead>
            <tr><th></th><th>User</th><th>Event</th><th>Recorded</th><th>Source</th><th>Status</th><th>Summary</th></tr>
          </thead>
          <tbody>
            {data?.items.length === 0 && <tr><td colSpan={7} className="muted">No attendances match these filters.</td></tr>}
            {data?.items.map((a) => (
              <tr key={a.id} className="clickable" onClick={() => setSelected(a)}>
                <td><AuthImage path={`/attendances/${a.id}/photo`} alt="" className="mini" /></td>
                <td>{a.user.full_name}<div className="small muted">{a.user.email}</div></td>
                <td>{a.event.title}<div className="small muted">{fmt(a.event.starts_at)}</div></td>
                <td>{fmt(a.submitted_at)}</td>
                <td><span className={`badge src-${a.source}`}>{a.source === 'ocr' ? 'Paper list' : 'Self'}</span></td>
                <td><StatusBadge status={a.status} late={a.is_late} /></td>
                <td className="truncate">{a.activity_summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && (
        <div className="pager">
          <span className="muted small">{data.total} result{data.total === 1 ? '' : 's'}</span>
          <button disabled={page <= 1} onClick={() => setFilter('page', String(page - 1))}>‹ Prev</button>
          <span className="small">Page {page} / {pages}</span>
          <button disabled={page >= pages} onClick={() => setFilter('page', String(page + 1))}>Next ›</button>
        </div>
      )}

      {selected && (
        <ReviewModal
          a={selected}
          onClose={() => setSelected(null)}
          onSaved={() => { setSelected(null); load() }}
        />
      )}
    </>
  )
}

function ReviewModal({ a, onClose, onSaved }: { a: Attendance; onClose: () => void; onSaved: () => void }) {
  const [comment, setComment] = useState(a.review_comment)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const remove = async () => {
    try {
      await api(`/admin/attendances/${a.id}`, { method: 'DELETE' })
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const review = async (status: AttendanceStatus) => {
    try {
      await api(`/admin/attendances/${a.id}`, json('PATCH', { status, review_comment: comment }))
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Modal title={`${a.user.full_name} — ${a.event.title}`} onClose={onClose}>
      <div className="review">
        <AuthImage path={`/attendances/${a.id}/photo`} alt="Attendance photo" className="full" />
        <dl>
          <dt>Status</dt><dd><StatusBadge status={a.status} late={a.is_late} /></dd>
          <dt>Submitted</dt><dd>{fmt(a.submitted_at)}</dd>
          <dt>Event start</dt><dd>{fmt(a.event.starts_at)}</dd>
          <dt>Activity</dt><dd>{a.activity_summary}</dd>
          <dt>Location</dt><dd>{a.location_note || '—'}</dd>
          <dt>Declaration</dt><dd>{a.declaration ? 'Confirmed' : 'No'}</dd>
          {a.reviewed_at && (<><dt>Reviewed</dt><dd>{fmt(a.reviewed_at)}</dd></>)}
        </dl>
      </div>
      <label>Review comment
        <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>
      <ErrorNote error={error} />
      {confirmDelete ? (
        <div className="confirm-delete">
          <span className="small">
            Delete this attendance record permanently?
            {a.source === 'ocr'
              ? ' The paper-list photo is kept for the other students on it.'
              : ' The check-in photo is deleted too, and the student can check in again while it is open.'}
          </span>
          <div className="row end">
            <button onClick={() => setConfirmDelete(false)}>Cancel</button>
            <button className="danger-solid" onClick={remove}>Delete record</button>
          </div>
        </div>
      ) : (
        <div className="row modal-actions">
          <button className="link danger" onClick={() => setConfirmDelete(true)}>🗑 Delete record</button>
          <div className="row">
            <button onClick={() => review('pending')}>Mark pending</button>
            <button className="danger" onClick={() => review('rejected')}>Reject</button>
            <button className="primary" onClick={() => review('approved')}>Approve</button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Insights({ summary: s, refreshing, onFilter, onFilters }: {
  summary: AttendanceSummary
  refreshing: boolean
  onFilter: (key: string, value: string) => void
  onFilters: (values: Record<string, string>) => void
}) {
  const approved = s.by_status.approved ?? 0
  const fromLists = s.by_source.ocr ?? 0
  const events = s.per_event.map((e) => ({
    id: e.event_id,
    label: shortDate(e.starts_at),
    title: `${e.title} · ${fmt(e.starts_at)}`,
    values: { self: e.count - e.from_lists, ocr: e.from_lists },
    marker: e.expected,
  }))
  const periodLabel = (iso: string) => {
    const d = new Date(`${iso}T12:00:00`)
    if (s.granularity === 'month') return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' })
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
  }
  const periodTitle = (iso: string) => {
    const d = new Date(`${iso}T12:00:00`)
    if (s.granularity === 'month') return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    if (s.granularity === 'week') return `Week of ${d.toLocaleDateString(undefined, { day: 'numeric', month: 'long' })}`
    return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
  }
  const trend = s.trend.map((p) => ({
    label: periodLabel(p.period),
    title: periodTitle(p.period),
    values: { self: p.self, ocr: p.ocr },
    late: p.late,
  }))
  const weekdays = WEEKDAYS.map((d, i) => ({ id: d, label: d, title: d, values: { n: s.by_weekday[i] ?? 0 } }))
  const turnout = s.avg_turnout === null ? '—' : `${Math.round(s.avg_turnout * 100)}%`
  // narrow the date range to one period of the trend
  const drillPeriod = (i: number) => {
    const p = s.trend[i]
    if (!p) return
    const start = new Date(`${p.period}T00:00:00`)
    const end = new Date(start)
    if (s.granularity === 'day') end.setDate(end.getDate())
    else if (s.granularity === 'week') end.setDate(end.getDate() + 6)
    else end.setMonth(end.getMonth() + 1, 0)
    onFilters({ date_from: localDay(start), date_to: localDay(end) })
  }

  if (s.total === 0 && s.events_in_scope === 0) {
    return <div className="card muted small insights-empty">No attendances match these filters, so there is nothing to chart.</div>
  }

  return (
    <div className={`insights ${refreshing ? 'stale' : ''}`} aria-busy={refreshing}>
      <div className="tiles">
        <div className="tile"><span className="tile-value">{s.total}</span><span className="tile-label">Attendances</span></div>
        <div className="tile" title="Average share of expected students present, over past events in scope">
          <span className="tile-value">{turnout}</span>
          <span className="tile-label">Avg turnout ({s.events_in_scope} event{s.events_in_scope === 1 ? '' : 's'})</span>
        </div>
        <div className="tile"><span className="tile-value">{pct(approved, s.total)}%</span>
          <span className="tile-label">Approved ({approved})</span></div>
        <div className="tile"><span className="tile-value">{pct(s.late, s.total)}%</span>
          <span className="tile-label">Late ({s.late})</span></div>
        <div className="tile"><span className="tile-value">{pct(fromLists, s.total)}%</span>
          <span className="tile-label">From paper lists ({fromLists})</span></div>
        <div className={`tile ${s.at_risk ? 'tile-alert' : ''}`} title="Below 50% attendance, with at least 2 expected events">
          <span className="tile-value">{s.at_risk ? `⚠ ${s.at_risk}` : '0'}</span>
          <span className="tile-label">Students below 50% (of {s.students_in_scope})</span>
        </div>
      </div>

      <div className="chart-grid">
        <ChartCard
          title="Attendance over time"
          subtitle={`Per ${s.granularity}, by event date · ${trend.length} period${trend.length === 1 ? '' : 's'}`}
          legend={<Legend series={SOURCE_SERIES} />}
          table={{
            head: ['Period', 'Self check-in', 'Paper list', 'Total', 'Late'],
            rows: s.trend.map((p) => [periodTitle(p.period), p.self, p.ocr, p.self + p.ocr, p.late]),
          }}
        >
          {trend.length === 0
            ? <p className="muted small">No attendances in this range.</p>
            : <LineChart data={trend} series={SOURCE_SERIES}
                extraTip={(d) => {
                  const total = (d.values.self ?? 0) + (d.values.ocr ?? 0)
                  const late = trend.find((t) => t.title === d.title)?.late ?? 0
                  return (
                    <>
                      <div className="viz-tip-total">Total<b>{total}</b></div>
                      <div>Late<b>{late}</b></div>
                    </>
                  )
                }} />}
          {trend.length > 1 && (
            <div className="small muted period-links">
              Zoom into: {trend.slice(-6).map((t, j) => (
                <button key={t.title} className="link small" onClick={() => drillPeriod(trend.length - Math.min(6, trend.length) + j)}>
                  {t.label}
                </button>
              ))}
            </div>
          )}
        </ChartCard>

        <ChartCard title="By weekday" subtitle="Attendances by the event's day of week"
          table={{ head: ['Day', 'Attendances'], rows: WEEKDAYS.map((d, i) => [d, s.by_weekday[i] ?? 0]) }}>
          <StackedColumns data={weekdays} series={[{ key: 'n', label: 'Attendances', color: 'var(--series-1)' }]}
            height={200} />
        </ChartCard>

        <ChartCard
          title="Attendance per event"
          subtitle={`${events.length} most recent event${events.length === 1 ? '' : 's'} · click a column to filter`}
          legend={<Legend series={SOURCE_SERIES} extra={<span><i className="viz-marker-key" />Expected</span>} />}
          table={{
            head: ['Event', 'Date', 'Self check-in', 'Paper list', 'Total', 'Expected', 'Turnout'],
            rows: s.per_event.map((e) => [e.title, fmt(e.starts_at), e.count - e.from_lists, e.from_lists, e.count,
              e.expected, e.expected ? `${pct(e.count, e.expected)}%` : '—']),
          }}
        >
          {events.length === 0
            ? <p className="muted small">No events with attendances in this range.</p>
            : <StackedColumns data={events} series={SOURCE_SERIES} markerLabel="Expected"
                onSelect={(d) => onFilter('event_id', String(d.id))} />}
        </ChartCard>

        <ChartCard
          title="Review status and source"
          table={{
            head: ['Breakdown', 'Count'],
            rows: [['Approved', approved], ['Pending', s.by_status.pending ?? 0], ['Rejected', s.by_status.rejected ?? 0],
              ['Self check-in', s.by_source.self ?? 0], ['Paper list', fromLists]],
          }}
        >
          <ShareStrip parts={[
            { key: 'approved', label: 'Approved', value: approved, color: 'var(--status-good)', icon: '✓' },
            { key: 'pending', label: 'Pending', value: s.by_status.pending ?? 0, color: 'var(--status-warning)', icon: '⏳' },
            { key: 'rejected', label: 'Rejected', value: s.by_status.rejected ?? 0, color: 'var(--status-critical)', icon: '✕' },
          ]} />
          <div className="strip-gap" />
          <ShareStrip parts={[
            { key: 'self', label: 'Self check-in', value: s.by_source.self ?? 0, color: 'var(--series-1)', icon: '' },
            { key: 'ocr', label: 'Paper list', value: fromLists, color: 'var(--series-2)', icon: '' },
          ]} />
          {(s.by_status.pending ?? 0) > 0 && (
            <button className="link small" onClick={() => onFilter('status', 'pending')}>
              Review {s.by_status.pending} pending →
            </button>
          )}
        </ChartCard>
      </div>

      <div className="chart-grid three">
        <ChartCard title="Group turnout" subtitle="Members present at the events meant for them · click to filter"
          table={{
            head: ['Group', 'Present', 'Expected', 'Rate'],
            rows: s.group_rates.map((g) => [g.group, g.attended, g.expected, `${Math.round(g.rate * 100)}%`]),
          }}>
          {s.group_rates.length === 0
            ? <p className="muted small">No groups among the students in scope.</p>
            : <RateBars data={s.group_rates.map((g) => ({ id: g.group_id, label: g.group, ...g }))}
                onSelect={(id) => onFilter('group_id', String(id))} />}
        </ChartCard>

        <ChartCard title="Lowest attendance" subtitle="Students most often absent · ⚠ below 50%"
          table={{
            head: ['Student', 'Present', 'Expected', 'Rate'],
            rows: s.students_low.map((u) => [u.full_name, u.attended, u.expected, `${Math.round(u.rate * 100)}%`]),
          }}>
          {s.students_low.length === 0
            ? <p className="muted small">No past events in scope.</p>
            : <RateBars data={s.students_low.map((u) => ({ id: u.user_id, label: u.full_name, ...u }))} threshold={0.5}
                onSelect={(id) => onFilter('user_id', String(id))} />}
        </ChartCard>

        <ChartCard title="Most present" subtitle="Highest attendance rate"
          table={{
            head: ['Student', 'Present', 'Expected', 'Rate'],
            rows: s.students_high.map((u) => [u.full_name, u.attended, u.expected, `${Math.round(u.rate * 100)}%`]),
          }}>
          {s.students_high.length === 0
            ? <p className="muted small">No past events in scope.</p>
            : <RateBars data={s.students_high.map((u) => ({ id: u.user_id, label: u.full_name, ...u }))}
                onSelect={(id) => onFilter('user_id', String(id))} />}
        </ChartCard>
      </div>
      <p className="small muted rates-note">
        Rates cover past events in the selected range and count any non-rejected attendance as present;
        status, source and late filters only change the volume charts.
      </p>
    </div>
  )
}
