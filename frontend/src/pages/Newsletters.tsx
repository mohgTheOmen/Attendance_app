import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, fmt, json, type NewsletterRecipients, type NewsletterThread } from '../api'
import { useAuth } from '../auth'
import { ErrorNote, Modal } from '../components'

export default function Newsletters() {
  const { user } = useAuth()
  const [items, setItems] = useState<NewsletterThread[] | null>(null)
  const [recipients, setRecipients] = useState<NewsletterRecipients>({ users: [], groups: [] })
  const [composing, setComposing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api<NewsletterThread[]>('/newsletters').then(setItems).catch((e) => setError(e.message))
  }, [])
  useEffect(() => {
    load()
    if (user?.role === 'admin') {
      api<NewsletterRecipients>('/newsletters/recipients').then(setRecipients).catch((e) => setError(e.message))
    }
  }, [load, user?.role])

  return (
    <>
      <div className="page-head newsletter-page-head">
        <div>
          <span className="newsletter-kicker">Class updates</span>
          <h2>Newsletters</h2>
          <p className="muted">Official announcements from your professors.</p>
        </div>
        {user?.role === 'admin' && <button className="primary" onClick={() => setComposing(true)}>Publish newsletter</button>}
      </div>
      <ErrorNote error={error} />
      <section className="newsletter-feed" aria-label="Published newsletters">
        {items === null && <div className="card muted">Loading newsletters…</div>}
        {items?.length === 0 && <div className="card newsletter-empty"><span aria-hidden="true">✦</span><h3>No announcements yet</h3><p className="muted">New newsletters from professors will appear here.</p></div>}
        {items?.map((newsletter, index) => {
          const message = newsletter.messages[0]
          return <article key={newsletter.id} className={`card newsletter-announcement ${index === 0 ? 'latest' : ''}`}>
            <header>
              <div className="newsletter-author-mark" aria-hidden="true">{newsletter.creator.full_name.charAt(0).toUpperCase()}</div>
              <div className="newsletter-byline"><strong>{newsletter.creator.full_name}</strong><span>Professor · {fmt(newsletter.created_at)}</span></div>
              <span className={`newsletter-audience ${newsletter.audience_all ? 'everyone' : ''}`}>{newsletter.audience_all ? 'Everyone' : newsletter.group?.name ?? 'Group'}</span>
            </header>
            <div className="newsletter-content">
              {index === 0 && <span className="newsletter-latest">Latest announcement</span>}
              <h3>{newsletter.subject}</h3>
              <p>{message?.body}</p>
            </div>
          </article>
        })}
      </section>
      {composing && <Compose recipients={recipients} onClose={() => setComposing(false)} onCreated={() => { setComposing(false); load() }} />}
    </>
  )
}

function Compose({ recipients, onClose, onCreated }: { recipients: NewsletterRecipients; onClose: () => void; onCreated: () => void }) {
  const [audience, setAudience] = useState('all')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [publishing, setPublishing] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setPublishing(true); setError(null)
    try {
      const payload = audience === 'all'
        ? { subject: subject.trim(), body: body.trim(), audience_all: true }
        : { subject: subject.trim(), body: body.trim(), group_id: Number(audience.split(':')[1]) }
      await api('/newsletters', json('POST', payload)); onCreated()
    } catch (err) { setError((err as Error).message); setPublishing(false) }
  }

  return <Modal title="Publish a newsletter" onClose={onClose}>
    <form className="form newsletter-compose" onSubmit={submit}>
      <p className="info">Students can read published newsletters but cannot create or reply to them.</p>
      <label>Audience<select required value={audience} onChange={(e) => setAudience(e.target.value)}><option value="all">Everyone</option>{recipients.groups.map((group) => <option key={group.id} value={`group:${group.id}`}>Group · {group.name}</option>)}</select></label>
      <label>Headline<input required maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Important class update" /></label>
      <label>Announcement<textarea required maxLength={5000} rows={10} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write the newsletter announcement…" /></label>
      <div className="small muted">{body.length} / 5000 characters</div>
      <ErrorNote error={error} />
      <div className="row end"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={publishing}>{publishing ? 'Publishing…' : 'Publish newsletter'}</button></div>
    </form>
  </Modal>
}
