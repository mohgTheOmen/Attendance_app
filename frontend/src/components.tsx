import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Navigate, Outlet } from 'react-router-dom'
import { fetchBlob, type AttendanceStatus, type Role } from './api'
import { useAuth } from './auth'

export function RequireAuth({ role }: { role?: Role }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="center muted">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  if (role && user.role !== role) return <Navigate to={user.role === 'admin' ? '/admin' : '/'} replace />
  return <Outlet />
}

export function Layout() {
  const { user, logout } = useAuth()
  const links =
    user?.role === 'admin'
      ? [
          ['/admin', 'Dashboard'],
          ['/admin/attendances', 'Attendances'],
          ['/admin/import', 'Import list'],
          ['/admin/events', 'Events'],
          ['/admin/users', 'Users'],
          ['/admin/groups', 'Groups'],
          ['/account', 'Account'],
        ]
      : [
          ['/', 'Events'],
          ['/history', 'My attendance'],
          ['/account', 'Account'],
        ]
  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">✓ Attendance</span>
        <nav>
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/' || to === '/admin'}>
              {label}
            </NavLink>
          ))}
        </nav>
        <span className="who">
          {user?.full_name}
          <button className="link" onClick={logout}>Sign out</button>
        </span>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}

export function StatusBadge({ status, late }: { status: AttendanceStatus; late?: boolean }) {
  return (
    <span className="badges">
      <span className={`badge ${status}`}>{status}</span>
      {late && <span className="badge late">late</span>}
    </span>
  )
}

/** Image that needs the bearer token, so it is fetched as a blob. */
export function AuthImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let url: string | null = null
    let cancelled = false
    fetchBlob(path)
      .then(({ blob }) => {
        if (cancelled) return
        url = URL.createObjectURL(blob)
        setSrc(url)
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [path])
  if (failed) return <div className={`photo-missing ${className ?? ''}`}>No photo</div>
  if (!src) return <div className={`photo-loading ${className ?? ''}`} />
  return <img src={src} alt={alt} className={className} />
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="link" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function ErrorNote({ error }: { error: string | null }) {
  return error ? <div className="error">{error}</div> : null
}
