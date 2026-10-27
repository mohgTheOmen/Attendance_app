import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  api, describeSeries, fmt, json, qs, WEEKDAYS,
  type EventItem, type Frequency, type GroupBrief, type User,
} from '../../api'
import { ErrorNote, Modal } from '../../components'

type Scope = 'this' | 'future' | 'all'

/** ISO -> value for <input type="datetime-local"> in local time */
const toLocalInput = (iso: string) => {
  const d = new Date(iso)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : null)
const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

export default function Events() {
  const [events, setEvents] = useState<EventItem[] | null>(null)
  const [groups, setGroups] = useState<GroupBrief[]>([])
  const [showPast, setShowPast] = useState(false)
  const [editing, setEditing] = useState<EventItem | 'new' | null>(null)
  const [deleting, setDeleting] = useState<EventItem | null>(null)
  const [absentFor, setAbsentFor] = useState<EventItem | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api<EventItem[]>('/events?scope=all').then(setEvents).catch((e) => setError(e.message))
    api<GroupBrief[]>('/admin/groups').then(setGroups).catch(() => {})
  }, [])
  useEffect(load, [load])

  const now = new Date()
  const state = (e: EventItem) =>
    e.check_in_open ? 'open' : new Date(e.check_in_opens_at) > now ? 'upcoming' : 'closed'
  const shown = (events ?? [])
    .filter((e) => showPast || new Date(e.check_in_closes_at) >= now)
    .sort((a, b) => (showPast ? b.starts_at.localeCompare(a.starts_at) : a.starts_at.localeCompare(b.starts_at)))

  return (
    <>
      <div className="page-head">
        <h2>Events</h2>
        <div className="row">
          <label className="inline small">
            <input type="checkbox" checked={showPast} onChange={(e) => setShowPast(e.target.checked)} /> Show past
          </label>
          <button className="primary" onClick={() => setEditing('new')}>+ New event</button>
        </div>
      </div>
      <ErrorNote error={error} />
      <div className="card table-wrap">
        <table>
          <thead>
            <tr><th>Title</th><th>Starts</th><th>Check-in window</th><th>Audience</th><th>State</th><th></th></tr>
          </thead>
          <tbody>
            {events && shown.length === 0 && (
              <tr><td colSpan={6} className="muted">{showPast ? 'No events yet.' : 'No current or upcoming events.'}</td></tr>
            )}
            {shown.map((e) => (
              <tr key={e.id}>
                <td>
                  <strong>{e.title}</strong>
                  {e.location && <div className="small muted">{e.location}</div>}
                  {e.series && <div className="small muted">🔁 {describeSeries(e.series)}</div>}
                </td>
                <td>{fmt(e.starts_at)}<div className="small muted">until {fmt(e.ends_at)}</div></td>
                <td className="small">{fmt(e.check_in_opens_at)} → {fmt(e.check_in_closes_at)}<br />
                  <span className="muted">late after {e.late_after_minutes} min</span></td>
                <td className="small">{e.groups.length ? e.groups.map((g) => g.name).join(', ') : <span className="muted">Everyone</span>}</td>
                <td><span className={`badge ${state(e)}`}>{state(e)}</span></td>
                <td className="actions">
                  <Link to={`/admin/attendances?event_id=${e.id}`}>Attendances</Link>
                  <Link to={`/admin/import?event_id=${e.id}`}>Import list</Link>
                  <button className="link" onClick={() => setAbsentFor(e)}>Absentees</button>
                  <button className="link" onClick={() => setEditing(e)}>Edit</button>
                  <button className="link danger" onClick={() => setDeleting(e)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <EventForm event={editing === 'new' ? null : editing} groups={groups} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }} />
      )}
      {deleting && (
        <DeleteEvent event={deleting} onClose={() => setDeleting(null)} onDone={() => { setDeleting(null); load() }} />
      )}
      {absentFor && <Absentees event={absentFor} onClose={() => setAbsentFor(null)} />}
    </>
  )
}

function ScopePicker({ value, onChange, verb }: { value: Scope; onChange: (s: Scope) => void; verb: string }) {
  return (
    <fieldset className="scope">
      <legend className="small">This is a recurring event. {verb}:</legend>
      {([['this', 'Only this occurrence'], ['future', 'This and following occurrences'], ['all', 'All occurrences']] as const)
        .map(([v, label]) => (
          <label key={v} className="check">
            <input type="radio" name="scope" checked={value === v} onChange={() => onChange(v)} /> {label}
          </label>
        ))}
    </fieldset>
  )
}

function EventForm({ event, groups, onClose, onSaved }: {
  event: EventItem | null; groups: GroupBrief[]; onClose: () => void; onSaved: () => void
}) {
  const [f, setF] = useState({
    title: event?.title ?? '',
    description: event?.description ?? '',
    location: event?.location ?? '',
    starts_at: event ? toLocalInput(event.starts_at) : '',
    ends_at: event ? toLocalInput(event.ends_at) : '',
    check_in_opens_at: event ? toLocalInput(event.check_in_opens_at) : '',
    check_in_closes_at: event ? toLocalInput(event.check_in_closes_at) : '',
    late_after_minutes: event ? String(event.late_after_minutes) : '',
  })
  const [groupIds, setGroupIds] = useState<Set<number>>(new Set(event?.groups.map((g) => g.id) ?? []))
  const [repeat, setRepeat] = useState<Frequency | 'none'>('none')
  const [interval, setInterval] = useState('1')
  const [weekdays, setWeekdays] = useState<Set<number>>(new Set())
  const [endMode, setEndMode] = useState<'count' | 'until'>('count')
  const [count, setCount] = useState('10')
  const [until, setUntil] = useState('')
  const [scope, setScope] = useState<Scope>('this')
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  const toggle = (s: Set<number>, v: number, apply: (s: Set<number>) => void) => {
    const next = new Set(s)
    if (next.has(v)) next.delete(v); else next.add(v)
    apply(next)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const times = {
      starts_at: fromLocalInput(f.starts_at),
      ends_at: fromLocalInput(f.ends_at),
      check_in_opens_at: fromLocalInput(f.check_in_opens_at),
      check_in_closes_at: fromLocalInput(f.check_in_closes_at),
    }
    const body: Record<string, unknown> = {
      title: f.title,
      description: f.description,
      location: f.location,
      late_after_minutes: f.late_after_minutes === '' ? null : Number(f.late_after_minutes),
      group_ids: [...groupIds],
    }
    try {
      if (event) {
        // Only send times that changed: they are applied as a shift across the chosen scope.
        for (const [k, v] of Object.entries(times)) {
          const orig = event[k as keyof typeof times]
          if (v && toLocalInput(v) !== toLocalInput(orig)) body[k] = v
        }
        await api(`/events/${event.id}${qs({ scope: event.series_id ? scope : undefined })}`, json('PATCH', body))
      } else {
        Object.assign(body, times)
        if (repeat !== 'none') {
          body.recurrence = {
            frequency: repeat,
            interval: Number(interval) || 1,
            weekdays: repeat === 'weekly' ? [...weekdays] : [],
            count: endMode === 'count' ? Number(count) : null,
            until: endMode === 'until' ? until : null,
            timezone: browserTz(),
          }
        }
        await api('/events', json('POST', body))
      }
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <Modal title={event ? 'Edit event' : 'New event'} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>Title *<input required maxLength={200} value={f.title} onChange={set('title')} /></label>
        <label>Location<input maxLength={200} value={f.location} onChange={set('location')} /></label>
        <label>Description<textarea rows={2} value={f.description} onChange={set('description')} /></label>
        <div className="two">
          <label>Starts *<input type="datetime-local" required value={f.starts_at} onChange={set('starts_at')} /></label>
          <label>Ends *<input type="datetime-local" required value={f.ends_at} onChange={set('ends_at')} /></label>
        </div>
        <div className="two">
          <label>Check-in opens <span className="muted small">(default 15 min before start)</span>
            <input type="datetime-local" value={f.check_in_opens_at} onChange={set('check_in_opens_at')} /></label>
          <label>Check-in closes <span className="muted small">(default: event end)</span>
            <input type="datetime-local" value={f.check_in_closes_at} onChange={set('check_in_closes_at')} /></label>
        </div>
        <label>Late after (minutes from start) <span className="muted small">(default 10)</span>
          <input type="number" min={0} max={1440} value={f.late_after_minutes} onChange={set('late_after_minutes')} />
        </label>

        <div>
          <strong className="small">Audience</strong>
          <span className="muted small"> — leave empty to open to everyone</span>
          <div className="chips">
            {groups.length === 0 && <span className="muted small">No groups yet. Create them under Groups.</span>}
            {groups.map((g) => (
              <label key={g.id} className={`chip ${groupIds.has(g.id) ? 'on' : ''}`}>
                <input type="checkbox" checked={groupIds.has(g.id)} onChange={() => toggle(groupIds, g.id, setGroupIds)} />
                {g.name}
              </label>
            ))}
          </div>
        </div>

        {!event && (
          <fieldset className="scope">
            <legend className="small">Repeat</legend>
            <div className="row">
              <select value={repeat} onChange={(e) => setRepeat(e.target.value as Frequency | 'none')}>
                <option value="none">Does not repeat</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
              {repeat !== 'none' && (
                <label className="inline">every
                  <input type="number" min={1} max={52} value={interval} onChange={(e) => setInterval(e.target.value)} style={{ width: 64 }} />
                  {{ daily: 'day(s)', weekly: 'week(s)', monthly: 'month(s)' }[repeat]}
                </label>
              )}
            </div>
            {repeat === 'weekly' && (
              <div className="chips">
                {WEEKDAYS.map((d, i) => (
                  <label key={d} className={`chip ${weekdays.has(i) ? 'on' : ''}`}>
                    <input type="checkbox" checked={weekdays.has(i)} onChange={() => toggle(weekdays, i, setWeekdays)} />
                    {d}
                  </label>
                ))}
                <span className="muted small">(none = same weekday as start)</span>
              </div>
            )}
            {repeat !== 'none' && (
              <div className="row">
                <label className="inline">
                  <input type="radio" checked={endMode === 'count'} onChange={() => setEndMode('count')} /> After
                  <input type="number" min={1} max={200} value={count} onChange={(e) => setCount(e.target.value)}
                    disabled={endMode !== 'count'} style={{ width: 72 }} /> occurrences
                </label>
                <label className="inline">
                  <input type="radio" checked={endMode === 'until'} onChange={() => setEndMode('until')} /> Until
                  <input type="date" value={until} onChange={(e) => setUntil(e.target.value)}
                    disabled={endMode !== 'until'} required={endMode === 'until'} />
                </label>
              </div>
            )}
            {repeat !== 'none' && <span className="muted small">Times follow {browserTz()} (max 200 occurrences).</span>}
          </fieldset>
        )}

        {event?.series && <ScopePicker value={scope} onChange={setScope} verb="Apply changes to" />}

        <ErrorNote error={error} />
        <div className="row end">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary">{event ? 'Save' : 'Create event'}</button>
        </div>
      </form>
    </Modal>
  )
}

function DeleteEvent({ event, onClose, onDone }: { event: EventItem; onClose: () => void; onDone: () => void }) {
  const [scope, setScope] = useState<Scope>('this')
  const [error, setError] = useState<string | null>(null)
  const remove = async () => {
    try {
      await api(`/events/${event.id}${qs({ scope: event.series_id ? scope : undefined })}`, { method: 'DELETE' })
      onDone()
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <Modal title={`Delete “${event.title}”`} onClose={onClose}>
      <p className="small">The attendance records and photos of deleted occurrences are removed too. This cannot be undone.</p>
      {event.series && <ScopePicker value={scope} onChange={setScope} verb="Delete" />}
      <ErrorNote error={error} />
      <div className="row end">
        <button onClick={onClose}>Cancel</button>
        <button className="danger" onClick={remove}>Delete</button>
      </div>
    </Modal>
  )
}

function Absentees({ event, onClose }: { event: EventItem; onClose: () => void }) {
  const [users, setUsers] = useState<User[] | null>(null)
  useEffect(() => {
    api<User[]>(`/admin/events/${event.id}/absentees`).then(setUsers).catch(() => setUsers([]))
  }, [event.id])
  return (
    <Modal title={`Not checked in — ${event.title}`} onClose={onClose}>
      {event.groups.length > 0 && (
        <p className="small muted">Expected: members of {event.groups.map((g) => g.name).join(', ')}</p>
      )}
      {!users && <p className="muted">Loading…</p>}
      {users?.length === 0 && <p className="muted">Everyone has checked in. 🎉</p>}
      <ul className="plain">
        {users?.map((u) => <li key={u.id}>{u.full_name} <span className="muted small">{u.email}</span></li>)}
      </ul>
    </Modal>
  )
}
