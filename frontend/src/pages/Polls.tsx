import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, json, type GroupBrief, type Poll } from '../api'
import { useAuth } from '../auth'
import { ErrorNote, Modal } from '../components'

type NewPoll = { subject: string; options: string[]; group_ids: number[] }

export default function Polls() {
  const { user } = useAuth()
  const admin = user?.role === 'admin'
  const [polls, setPolls] = useState<Poll[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [busyPoll, setBusyPoll] = useState<number | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const mutation = useRef(false)
  const generation = useRef(0)
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    const load = async () => {
      const currentGeneration = generation.current
      try {
        if (!mutation.current) {
          const result = await api<Poll[]>('/polls', { signal: controller.signal })
          if (!cancelled && currentGeneration === generation.current) {
            setPolls(result)
            setError(null)
          }
        }
      } catch (err) {
        if (!cancelled && currentGeneration === generation.current) setError((err as Error).message)
      } finally {
        if (!cancelled) timer = setTimeout(load, 5000)
      }
    }
    void load()
    return () => { cancelled = true; controller.abort(); clearTimeout(timer) }
  }, [refreshKey])

  const changePoll = async (path: string, body: unknown, pollId: number | null) => {
    if (mutation.current) throw new Error('Please wait for the current action to finish.')
    mutation.current = true
    generation.current += 1 // Discard any GET response that started before this mutation.
    setBusyPoll(pollId)
    setError(null)
    try {
      const result = await api<Poll>(path, json('POST', body))
      if (mounted.current) setPolls((items) => [result, ...(items ?? []).filter((p) => p.id !== result.id)]
        .sort((a, b) => b.id - a.id))
    } finally {
      mutation.current = false
      if (mounted.current) { setBusyPoll(null); setRefreshKey((key) => key + 1) }
    }
  }

  const vote = async (pollId: number, optionId: number) => {
    try { await changePoll(`/polls/${pollId}/votes`, { option_id: optionId }, pollId) }
    catch (err) { if (mounted.current) setError((err as Error).message) }
  }

  const close = async (poll: Poll) => {
    if (!confirm(`Close "${poll.subject}"? Students will no longer be able to vote.`)) return
    try { await changePoll(`/polls/${poll.id}/close`, {}, poll.id) }
    catch (err) { if (mounted.current) setError((err as Error).message) }
  }

  return (
    <>
      <div className="page-head">
        <h2>Voting</h2>
        {admin && <button className="primary" onClick={() => setCreating(true)}>+ New poll</button>}
      </div>
      <p className="muted small">
        One choice per student per poll. Submitted votes cannot be changed.
        Results show totals only, without voter names, and refresh every 5 seconds.
      </p>
      <ErrorNote error={error} />
      {polls === null && !error && <p className="muted" role="status">Loading polls…</p>}
      {polls === null && error && <button onClick={() => setRefreshKey((key) => key + 1)}>Retry loading</button>}
      {polls?.length === 0 && <div className="card muted">{admin
        ? 'No polls yet. Create a poll for one or more groups.'
        : 'No polls are available for your groups yet.'}</div>}
      <div className="list">
        {polls?.map((poll) => <PollCard key={poll.id} poll={poll} admin={admin}
          busy={busyPoll === poll.id} onVote={vote} onClose={close} />)}
      </div>
      {creating && <CreatePoll onClose={() => setCreating(false)} onCreate={async (body) => {
        await changePoll('/polls', body, null)
        if (mounted.current) setCreating(false)
      }} />}
    </>
  )
}

function PollCard({ poll, admin, busy, onVote, onClose }: {
  poll: Poll; admin: boolean; busy: boolean
  onVote: (pollId: number, optionId: number) => Promise<void>
  onClose: (poll: Poll) => Promise<void>
}) {
  const [selected, setSelected] = useState<number | null>(null)
  const canVote = !admin && poll.is_open && !poll.has_voted
  return (
    <article className="card poll" aria-labelledby={`poll-${poll.id}`}>
      <div className="event-head">
        <h3 id={`poll-${poll.id}`}>{poll.subject}</h3>
        <span className={`badge ${poll.is_open ? 'open' : ''}`}>{poll.is_open ? 'Open' : 'Closed'}</span>
      </div>
      <p className="small muted">Groups: {poll.groups.map((g) => g.name).join(', ') || 'No eligible groups remain'}</p>
      <form className="form" onSubmit={(event) => {
        event.preventDefault()
        if (canVote && !busy && selected !== null) void onVote(poll.id, selected)
      }}>
        <fieldset className="scope" disabled={!canVote || busy}>
          <legend>{canVote ? 'Choose one option' : 'Results'}</legend>
          {poll.options.map((option) => {
            const percent = poll.total_votes ? Math.round(option.vote_count / poll.total_votes * 100) : 0
            return <div className="poll-option" key={option.id}>
              <div className="poll-option-head">
                {canVote ? <label className="inline">
                  <input type="radio" name={`poll-${poll.id}`} required value={option.id}
                    checked={selected === option.id} onChange={() => setSelected(option.id)} />
                  {option.label}
                </label> : <span>{option.label}</span>}
                <span className="small">{option.vote_count} {option.vote_count === 1 ? 'vote' : 'votes'} · {percent}%</span>
              </div>
              <progress className="poll-progress" value={option.vote_count} max={poll.total_votes || 1}
                aria-label={`${option.label}: ${option.vote_count} votes, ${percent}%`} />
            </div>
          })}
        </fieldset>
        <div className="row">
          <strong className="small">{poll.total_votes} total {poll.total_votes === 1 ? 'vote' : 'votes'}</strong>
          {canVote && <button className="primary" disabled={selected === null || busy}>
            {busy ? 'Submitting…' : 'Submit vote'}
          </button>}
          {admin && poll.is_open && <button type="button" disabled={busy} onClick={() => void onClose(poll)}>
            {busy ? 'Closing…' : 'Close poll'}
          </button>}
        </div>
        {!admin && poll.has_voted && <p className="success" role="status">Your vote has been recorded.</p>}
        {!poll.is_open && <p className="muted small">Voting has closed. Final results remain available.</p>}
      </form>
    </article>
  )
}

function CreatePoll({ onClose, onCreate }: { onClose: () => void; onCreate: (body: NewPoll) => Promise<void> }) {
  const [groups, setGroups] = useState<GroupBrief[] | null>(null)
  const [subject, setSubject] = useState('')
  const [options, setOptions] = useState(['', ''])
  const [groupIds, setGroupIds] = useState<number[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    api<GroupBrief[]>('/admin/groups', { signal: controller.signal }).then(setGroups).catch((err) => {
      if (!controller.signal.aborted) setError((err as Error).message)
    })
    return () => controller.abort()
  }, [])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (pending.current) return
    const clean = options.map((option) => option.trim())
    if (!subject.trim() || clean.some((option) => !option) || !groupIds.length) {
      setError('Enter a subject, fill every option, and select at least one group.'); return
    }
    if (new Set(clean.map((option) => option.toLocaleLowerCase())).size !== clean.length) {
      setError('Each option must be different.'); return
    }
    pending.current = true
    setBusy(true)
    setError(null)
    try { await onCreate({ subject: subject.trim(), options: clean, group_ids: groupIds }) }
    catch (err) { setError((err as Error).message) }
    finally { pending.current = false; setBusy(false) }
  }

  return <Modal title="New poll" onClose={() => { if (!busy) onClose() }}>
    <form className="form" onSubmit={submit}>
      <fieldset className="scope" disabled={busy}>
        <label>Subject<input required maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
        {options.map((option, index) => <div className="row" key={index}>
          <label className="poll-option-input">Option {index + 1}<input required maxLength={200} value={option}
            onChange={(e) => setOptions((items) => items.map((item, i) => i === index ? e.target.value : item))} /></label>
          {options.length > 2 && <button type="button" aria-label={`Remove option ${index + 1}`}
            onClick={() => setOptions((items) => items.filter((_, i) => i !== index))}>Remove</button>}
        </div>)}
        <button type="button" disabled={options.length >= 20} onClick={() => setOptions((items) => [...items, ''])}>+ Add option</button>
      </fieldset>
      <fieldset className="scope" disabled={busy}>
        <legend>Eligible groups (select at least one)</legend>
        {groups === null && !error && <p className="muted">Loading groups…</p>}
        {groups?.length === 0 && <p className="muted">Create a group in <Link to="/admin/groups">Groups</Link> before opening a poll.</p>}
        {groups?.map((group) => <label className="check" key={group.id}>
          <input type="checkbox" checked={groupIds.includes(group.id)} onChange={(e) => setGroupIds((ids) =>
            e.target.checked ? [...ids, group.id] : ids.filter((id) => id !== group.id))} />
          {group.name}
        </label>)}
      </fieldset>
      <p className="small muted">The poll opens immediately. Options and submitted votes cannot be changed.</p>
      <ErrorNote error={error} />
      <div className="row end">
        <button type="button" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !groups?.length || !groupIds.length}>{busy ? 'Opening…' : 'Open poll'}</button>
      </div>
    </form>
  </Modal>
}
