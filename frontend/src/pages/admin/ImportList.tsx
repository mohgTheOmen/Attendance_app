import { useCallback, useEffect, useMemo, useState, type DragEvent, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api, browserTz, fmt, json, qs,
  type EventItem, type OcrImport, type OcrImportBrief, type OcrLine, type OcrStatus, type User,
} from '../../api'
import { AuthImage, ErrorNote, Modal } from '../../components'

const MAX_FILES = 10

/* ------------------------------------------------------------------ upload -- */

export default function ImportList() {
  const { importId } = useParams()
  return importId ? <Review importId={Number(importId)} /> : <Upload />
}

function Upload() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [files, setFiles] = useState<File[]>([])
  const [previews, setPreviews] = useState<string[]>([])
  const [events, setEvents] = useState<EventItem[]>([])
  const [eventId, setEventId] = useState(params.get('event_id') ?? '')
  const [engines, setEngines] = useState<Record<string, boolean>>({ tesseract: true })
  const [engine, setEngine] = useState('tesseract')
  const [recent, setRecent] = useState<OcrImportBrief[]>([])
  const [deleting, setDeleting] = useState<OcrImportBrief | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<EventItem[]>('/events?scope=all').then(setEvents).catch(() => {})
    api<Record<string, boolean>>('/admin/ocr/engines').then(setEngines).catch(() => {})
    api<OcrImportBrief[]>('/admin/ocr/imports').then(setRecent).catch(() => {})
  }, [])

  useEffect(() => {
    const urls = files.map((f) => URL.createObjectURL(f))
    setPreviews(urls)
    return () => urls.forEach((u) => URL.revokeObjectURL(u))
  }, [files])

  const add = (list: FileList | null) => {
    if (!list) return
    const images = [...list].filter((f) => /^image\/(jpeg|png|webp)$/.test(f.type))
    if (images.length < list.length) setError('Only JPEG, PNG and WebP images are accepted.')
    else setError(null)
    setFiles((prev) => [...prev, ...images].slice(0, MAX_FILES))
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    add(e.dataTransfer.files)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!files.length) return setError('Add at least one photo of the list.')
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    if (eventId) fd.set('event_id', eventId)
    fd.set('engine', engine)
    fd.set('tz', browserTz())
    setBusy(true)
    setError(null)
    try {
      const imp = await api<OcrImport>('/admin/ocr/imports', { method: 'POST', body: fd })
      navigate(`/admin/import/${imp.id}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // newest first, recent events most likely
  const eventOptions = [...events].sort((a, b) => b.starts_at.localeCompare(a.starts_at))

  return (
    <div className="narrow wide-ish">
      <h2>Import a paper attendance list</h2>
      <p className="muted small">
        Upload one or more photos of a signed list. The names are read automatically and matched to enrolled
        students; anything unclear (the date or a name) is left for you to decide before anything is saved.
      </p>
      <form className="card form" onSubmit={submit}>
        <label
          className={`dropzone ${dragging ? 'over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple
            onChange={(e) => { add(e.target.files); e.target.value = '' }} />
          <strong>Drop photos here or click to choose</strong>
          <span className="muted small">Up to {MAX_FILES} images · JPEG, PNG or WebP · one list may span several photos</span>
        </label>

        {files.length > 0 && (
          <div className="thumbs">
            {previews.map((src, i) => (
              <figure key={src} className="thumb-card">
                <img src={src} alt={files[i].name} />
                <figcaption className="small">
                  <span className="truncate">{files[i].name}</span>
                  <button type="button" className="link danger"
                    onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label="Remove">✕</button>
                </figcaption>
              </figure>
            ))}
          </div>
        )}

        <label>Event <span className="muted small">(optional — leave empty to detect it from the date on the sheet)</span>
          <select value={eventId} onChange={(e) => setEventId(e.target.value)}>
            <option value="">Detect from the list</option>
            {eventOptions.map((e) => <option key={e.id} value={e.id}>{e.title} — {fmt(e.starts_at)}</option>)}
          </select>
        </label>

        {engines.azure && (
          <label>Reader
            <select value={engine} onChange={(e) => setEngine(e.target.value)}>
              <option value="tesseract">Tesseract (local)</option>
              <option value="azure">Azure OpenAI (vision model)</option>
            </select>
          </label>
        )}
        {!engines.tesseract && engine === 'tesseract' && (
          <div className="error">Tesseract is not installed on the server.</div>
        )}

        <ErrorNote error={error} />
        <button className="primary" disabled={busy || !files.length}>
          {busy ? 'Reading the list…' : `Read ${files.length || ''} photo${files.length === 1 ? '' : 's'}`}
        </button>
      </form>

      {recent.length > 0 && (
        <>
          <h3>Recent imports</h3>
          <div className="card table-wrap">
            <table>
              <thead><tr><th>Uploaded</th><th>Event</th><th>Photos</th><th>Lines</th><th>Saved</th><th></th></tr></thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id}>
                    <td>{fmt(r.created_at)}</td>
                    <td>{r.event_title ?? <span className="muted">Not chosen</span>}</td>
                    <td>{r.image_count}</td>
                    <td>{r.line_count}</td>
                    <td>{r.created_attendances}</td>
                    <td className="actions">
                      <Link to={`/admin/import/${r.id}`}>{r.committed_at ? 'Open' : 'Continue review'}</Link>
                      <button className="link danger" onClick={() => setDeleting(r)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {deleting && (
            <DeleteImport
              importId={deleting.id}
              savedCount={deleting.created_attendances}
              label={`${deleting.event_title ?? 'unassigned list'} · uploaded ${fmt(deleting.created_at)}`}
              onClose={() => setDeleting(null)}
              onDeleted={() => { setRecent((rs) => rs.filter((x) => x.id !== deleting.id)); setDeleting(null) }}
            />
          )}
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ review -- */

const STATUS_LABEL: Record<OcrStatus, string> = {
  matched: 'Matched',
  review: 'Check',
  unmatched: 'Not recognised',
  duplicate: 'Duplicate',
  already_present: 'Already recorded',
  ignored: 'Ignored',
}

interface Choice {
  checked: boolean
  userId: number | null
}

const initialChoice = (l: OcrLine): Choice => ({
  checked: l.status === 'matched' || l.status === 'review',
  userId: l.user_id,
})

type View = 'all' | 'attention' | 'selected'

function Review({ importId }: { importId: number }) {
  const navigate = useNavigate()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [imp, setImp] = useState<OcrImport | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [choices, setChoices] = useState<Record<number, Choice>>({})
  const [extra, setExtra] = useState<number[]>([]) // students added by hand, not on any line
  const [image, setImage] = useState(0)
  const [view, setView] = useState<View>('all')
  const [showIgnored, setShowIgnored] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<{ created: number; skipped: number; eventId: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const apply = useCallback((data: OcrImport) => {
    setImp(data)
    setChoices(Object.fromEntries(data.lines.map((l) => [l.index, initialChoice(l)])))
  }, [])

  /** After adding photos or saving: keep the admin's decisions on existing lines, but untick
      anyone who is now recorded; new lines get their default selection. */
  const merge = (data: OcrImport) => {
    setImp(data)
    setChoices((prev) => Object.fromEntries(data.lines.map((l) => {
      const old = prev[l.index]
      if (!old) return [l.index, initialChoice(l)]
      return [l.index, l.status === 'already_present' ? { ...old, checked: false } : old]
    })))
  }

  const [adding, setAdding] = useState(false)
  const addPhotos = async (list: FileList | null) => {
    if (!list?.length || !imp) return
    const fd = new FormData()
    ;[...list].forEach((f) => fd.append('files', f))
    fd.set('tz', browserTz())
    setAdding(true)
    setError(null)
    try {
      const firstNew = imp.image_count
      merge(await api<OcrImport>(`/admin/ocr/imports/${imp.id}/images`, { method: 'POST', body: fd }))
      setImage(firstNew)
      setSaved(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setAdding(false)
    }
  }

  useEffect(() => {
    api<OcrImport>(`/admin/ocr/imports/${importId}${qs({ tz: browserTz() })}`).then(apply).catch((e) => setError(e.message))
    api<User[]>('/admin/users?include_inactive=false').then((u) => setUsers(u.filter((x) => x.role === 'user')))
      .catch(() => {})
  }, [importId, apply])

  const chooseEvent = async (eventId: number) => {
    setError(null)
    try {
      // re-match: flags who already has an attendance and who is outside the event's groups
      apply(await api<OcrImport>(`/admin/ocr/imports/${importId}${qs({ tz: browserTz() })}`,
        json('PATCH', { event_id: eventId })))
      setSaved(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const set = (index: number, patch: Partial<Choice>) =>
    setChoices((c) => ({ ...c, [index]: { ...c[index], ...patch } }))

  const userName = useMemo(() => new Map(users.map((u) => [u.id, u.full_name])), [users])

  // Who is selected on which line; the same student picked twice is only saved once.
  const selected = useMemo(() => {
    if (!imp) return []
    const seen = new Set<number>()
    const out: { user_id: number; line_index?: number }[] = []
    for (const l of imp.lines) {
      const c = choices[l.index]
      if (c?.checked && c.userId && !seen.has(c.userId)) {
        seen.add(c.userId)
        out.push({ user_id: c.userId, line_index: l.index })
      }
    }
    for (const uid of extra) if (!seen.has(uid)) { seen.add(uid); out.push({ user_id: uid }) }
    return out
  }, [imp, choices, extra])

  const pickedBy = useMemo(() => {
    const m = new Map<number, number[]>()
    if (imp) for (const l of imp.lines) {
      const c = choices[l.index]
      if (c?.checked && c.userId) m.set(c.userId, [...(m.get(c.userId) ?? []), l.index])
    }
    return m
  }, [imp, choices])

  if (!imp) return error ? <ErrorNote error={error} /> : <p className="muted">Loading…</p>

  const event = imp.event
  const ignored = imp.lines.filter((l) => l.status === 'ignored')
  const visible = imp.lines.filter((l) => {
    if (l.status === 'ignored') return showIgnored
    if (view === 'attention') return l.status === 'review' || l.status === 'unmatched' || l.status === 'duplicate'
    if (view === 'selected') return choices[l.index]?.checked
    return true
  })
  const attention = imp.lines.filter((l) => l.status === 'review' || l.status === 'unmatched').length

  const save = async () => {
    if (!imp.event_id) return setError('Choose the event this list belongs to first.')
    setSaving(true)
    setError(null)
    try {
      const r = await api<{ created: number; skipped_existing: number }>(
        `/admin/ocr/imports/${imp.id}/commit`, json('POST', { event_id: imp.event_id, entries: selected }))
      setSaved({ created: r.created, skipped: r.skipped_existing, eventId: imp.event_id })
      // refresh: saved students now show as already recorded, so adding photos later just adds the rest
      merge(await api<OcrImport>(`/admin/ocr/imports/${imp.id}${qs({ tz: browserTz() })}`))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/admin/import" className="small">← New import</Link>
          <h2>Review list #{imp.id}</h2>
        </div>
        <button className="danger" onClick={() => setConfirmDelete(true)}>🗑 Delete list</button>
      </div>
      {confirmDelete && (
        <DeleteImport
          importId={imp.id}
          savedCount={imp.created_attendances}
          label={`list #${imp.id}${imp.event ? ` · ${imp.event.title}` : ''}`}
          onClose={() => setConfirmDelete(false)}
          onDeleted={() => navigate('/admin/import', { replace: true })}
        />
      )}

      <div className="import-layout">
        <aside className="card import-images">
          {imp.image_count > 1 && (
            <div className="tabs">
              {Array.from({ length: imp.image_count }, (_, i) => (
                <button key={i} className={i === image ? 'on' : ''} onClick={() => setImage(i)}>Photo {i + 1}</button>
              ))}
            </div>
          )}
          <a href="#" onClick={(e) => e.preventDefault()} title="Scroll to zoom in your browser">
            <AuthImage path={`/admin/ocr/imports/${imp.id}/images/${image}`} alt={`List photo ${image + 1}`} className="sheet" />
          </a>
          <label className={`add-photos ${adding ? 'busy' : ''}`}>
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={adding}
              onChange={(e) => { addPhotos(e.target.files); e.target.value = '' }} />
            {adding ? 'Reading new photos…' : '+ Add more photos'}
            <span className="muted small">another page or the back of the sheet — new names are added below</span>
          </label>
        </aside>

        <section className="import-main">
          <DateAndEvent imp={imp} onChoose={chooseEvent} />

          <div className="card">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div className="seg" role="tablist">
                {([['all', `All (${imp.lines.length - ignored.length})`], ['attention', `Needs a decision (${attention})`],
                  ['selected', `Selected (${selected.length})`]] as const).map(([v, label]) => (
                  <button key={v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>{label}</button>
                ))}
              </div>
              {ignored.length > 0 && (
                <label className="inline small">
                  <input type="checkbox" checked={showIgnored} onChange={(e) => setShowIgnored(e.target.checked)} />
                  Show {ignored.length} ignored line{ignored.length === 1 ? '' : 's'} (dates, headers, grades)
                </label>
              )}
            </div>

            <div className="table-wrap">
              <table className="lines">
                <thead>
                  <tr><th></th><th>Written on the list</th><th>Student</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {visible.length === 0 && <tr><td colSpan={4} className="muted">Nothing here.</td></tr>}
                  {visible.map((l) => {
                    const c = choices[l.index] ?? initialChoice(l)
                    const twice = c.checked && c.userId ? (pickedBy.get(c.userId)?.length ?? 0) > 1 : false
                    return (
                      <tr key={l.index} className={`line-${l.status} ${c.checked ? 'is-checked' : ''}`}>
                        <td>
                          <input type="checkbox" aria-label="Include" checked={c.checked}
                            disabled={!c.userId || l.status === 'already_present'}
                            onChange={(e) => set(l.index, { checked: e.target.checked })} />
                        </td>
                        <td>
                          <code className="ocr">{l.raw}</code>
                          {imp.image_count > 1 && <div className="small muted">photo {l.image_index + 1}</div>}
                        </td>
                        <td>
                          <StudentSelect line={l} users={users} value={c.userId}
                            onChange={(uid) => set(l.index, { userId: uid, checked: uid !== null })} />
                          {twice && <div className="small warn">Also selected on another line — saved once</div>}
                          {c.userId && !l.in_audience && c.userId === l.user_id && (
                            <div className="small warn">Not in this event's groups</div>
                          )}
                        </td>
                        <td>
                          <span className={`badge ocr-${l.status}`}>{STATUS_LABEL[l.status]}</span>
                          {l.user_id && l.status !== 'ignored' && <div className="small muted">{Math.round(l.score)}% match</div>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <AddStudent users={users} exclude={new Set(selected.map((s) => s.user_id))}
              onAdd={(uid) => setExtra((x) => [...x, uid])} />
            {extra.length > 0 && (
              <div className="chips">
                {extra.map((uid) => (
                  <span key={uid} className="chip on">
                    {userName.get(uid)}
                    <button className="link" onClick={() => setExtra(extra.filter((x) => x !== uid))} aria-label="Remove">✕</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>

      <div className="savebar">
        <ErrorNote error={error} />
        {saved ? (
          <div className="success row">
            Saved {saved.created} attendance{saved.created === 1 ? '' : 's'}
            {saved.skipped > 0 && `, ${saved.skipped} already recorded`}.
            <Link to={`/admin/attendances?event_id=${saved.eventId}&source=ocr`}>View in Attendances →</Link>
            <span className="muted small">To record another session from this sheet, choose a different event above.</span>
          </div>
        ) : (
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span>
              <strong>{selected.length}</strong> student{selected.length === 1 ? '' : 's'} selected
              {event ? <> for <strong>{event.title}</strong> ({fmt(event.starts_at)})</> : <span className="warn"> — choose the event first</span>}
            </span>
            <button className="primary" disabled={!imp.event_id || !selected.length || saving} onClick={save}>
              {saving ? 'Saving…' : `Save ${selected.length} attendance${selected.length === 1 ? '' : 's'}`}
            </button>
          </div>
        )}
      </div>
    </>
  )
}

/* ------------------------------------------------------- date / event panel -- */

const todayIso = () => {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}
const longDate = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

function DateAndEvent({ imp, onChoose }: { imp: OcrImport; onChoose: (eventId: number) => void }) {
  const initial = imp.detected_date ?? imp.photo_date ?? ''
  const [day, setDay] = useState(initial || todayIso())
  const [events, setEvents] = useState<EventItem[]>(imp.suggested_events)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!day) return
    let cancelled = false
    api<EventItem[]>(`/admin/ocr/events${qs({ date: day, tz: browserTz() })}`)
      .then((e) => !cancelled && setEvents(e)).catch(() => {})
    return () => { cancelled = true }
  }, [day])

  const chosen = imp.event

  return (
    <div className={`card date-panel ${imp.event_id ? '' : 'needs'}`}>
      <div className="date-source small">
        {imp.detected_date ? (
          <>📅 Date read from the sheet: <strong>{longDate(imp.detected_date)}</strong>
            {imp.date_text && <span className="muted"> (from “{imp.date_text}”)</span>}</>
        ) : imp.photo_date ? (
          <span className="warn">⚠ No date could be read from the sheet. The photo was taken on <strong>{longDate(imp.photo_date)}</strong> — check it is the right day.</span>
        ) : (
          <span className="warn">⚠ No date could be read from the sheet. Pick the day of the event.</span>
        )}
      </div>

      <div className="row">
        <label className="inline">Day <input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
        {chosen && <span className="small">Recording for <strong>{chosen.title}</strong> · {fmt(chosen.starts_at)}</span>}
      </div>

      <div className="event-choices">
        {events.length === 0 && <span className="muted small">No events on this day.</span>}
        {events.map((e) => (
          <label key={e.id} className={`event-choice ${imp.event_id === e.id ? 'on' : ''}`}>
            <input type="radio" name="event" checked={imp.event_id === e.id} onChange={() => onChoose(e.id)} />
            <span>
              <strong>{e.title}</strong>
              <span className="small muted"> {new Date(e.starts_at).toLocaleTimeString(undefined, { timeStyle: 'short' })}–{new Date(e.ends_at).toLocaleTimeString(undefined, { timeStyle: 'short' })}</span>
              {e.groups.length > 0 && <span className="small muted"> · {e.groups.map((g) => g.name).join(', ')}</span>}
            </span>
          </label>
        ))}
        {!creating && <button className="link" onClick={() => setCreating(true)}>+ Create an event on this day</button>}
      </div>
      {creating && (
        <QuickEvent day={day} onCancel={() => setCreating(false)} onError={setError}
          onCreated={(e) => { setCreating(false); setEvents((ev) => [...ev, e]); onChoose(e.id) }} />
      )}
      <ErrorNote error={error} />
    </div>
  )
}

function QuickEvent({ day, onCreated, onCancel, onError }: {
  day: string; onCreated: (e: EventItem) => void; onCancel: () => void; onError: (m: string) => void
}) {
  const [title, setTitle] = useState('')
  const [start, setStart] = useState('09:00')
  const [end, setEnd] = useState('11:00')
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const at = (t: string) => new Date(`${day}T${t}`).toISOString()
    try {
      // a past event: open the check-in window over the whole event so it isn't flagged oddly
      const [created] = await api<EventItem[]>('/events', json('POST', {
        title, starts_at: at(start), ends_at: at(end), check_in_opens_at: at(start), check_in_closes_at: at(end),
      }))
      onCreated(created)
    } catch (err) {
      onError((err as Error).message)
    }
  }
  return (
    <form className="row quick-event" onSubmit={submit}>
      <input required placeholder="Event title, e.g. Seminar S1" value={title} onChange={(e) => setTitle(e.target.value)} />
      <input type="time" required value={start} onChange={(e) => setStart(e.target.value)} aria-label="Start" />
      <span className="muted">–</span>
      <input type="time" required value={end} onChange={(e) => setEnd(e.target.value)} aria-label="End" />
      <button className="primary">Create &amp; use</button>
      <button type="button" className="link" onClick={onCancel}>Cancel</button>
    </form>
  )
}

/* -------------------------------------------------------------- selectors -- */

function StudentSelect({ line, users, value, onChange }: {
  line: OcrLine; users: User[]; value: number | null; onChange: (uid: number | null) => void
}) {
  const suggested = new Set(line.suggestions.map((s) => s.user_id))
  return (
    <select className={value ? '' : 'empty'} value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">— nobody / skip —</option>
      {line.suggestions.length > 0 && (
        <optgroup label="Best guesses">
          {line.suggestions.map((s) => (
            <option key={s.user_id} value={s.user_id}>{s.full_name} ({Math.round(s.score)}%)</option>
          ))}
        </optgroup>
      )}
      <optgroup label="All students">
        {users.filter((u) => !suggested.has(u.id)).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
      </optgroup>
    </select>
  )
}

function AddStudent({ users, exclude, onAdd }: { users: User[]; exclude: Set<number>; onAdd: (uid: number) => void }) {
  const [value, setValue] = useState('')
  return (
    <div className="row add-student">
      <span className="small muted">Present but missing from the photo?</span>
      <select value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">Add a student…</option>
        {users.filter((u) => !exclude.has(u.id)).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
      </select>
      <button disabled={!value} onClick={() => { onAdd(Number(value)); setValue('') }}>Add</button>
    </div>
  )
}

/* ------------------------------------------------------------ delete list -- */

function DeleteImport({ importId, savedCount, label, onClose, onDeleted }: {
  importId: number; savedCount: number; label: string; onClose: () => void; onDeleted: () => void
}) {
  const [withAttendances, setWithAttendances] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const remove = async () => {
    setBusy(true)
    try {
      await api(`/admin/ocr/imports/${importId}${qs({ delete_attendances: withAttendances || undefined })}`,
        { method: 'DELETE' })
      onDeleted()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }
  return (
    <Modal title="Delete imported list" onClose={onClose}>
      <p className="small">Delete <strong>{label}</strong>, with its photos and OCR results? This cannot be undone.</p>
      {savedCount > 0 ? (
        <fieldset className="scope">
          <legend className="small">{savedCount} attendance{savedCount === 1 ? ' was' : 's were'} saved from this list</legend>
          <label className="check">
            <input type="radio" name="del-att" checked={!withAttendances} onChange={() => setWithAttendances(false)} />
            <span>Keep them <span className="muted small">— they stay recorded and keep showing the list photo</span></span>
          </label>
          <label className="check">
            <input type="radio" name="del-att" checked={withAttendances} onChange={() => setWithAttendances(true)} />
            <span>Delete them too <span className="muted small">— e.g. the list was for the wrong event</span></span>
          </label>
        </fieldset>
      ) : (
        <p className="small muted">No attendances were saved from it.</p>
      )}
      <ErrorNote error={error} />
      <div className="row end">
        <button onClick={onClose}>Cancel</button>
        <button className="danger-solid" disabled={busy} onClick={remove}>
          {busy ? 'Deleting…' : withAttendances ? `Delete list and ${savedCount} attendance${savedCount === 1 ? '' : 's'}` : 'Delete list'}
        </button>
      </div>
    </Modal>
  )
}
