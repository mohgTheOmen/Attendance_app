import { useMemo, useRef, useState, type ReactNode } from 'react'

/* Small, dependency-free SVG charts. Colors come from CSS roles (--series-1, --status-*),
   so light/dark are handled in index.css. Every chart has a hover tooltip and a table view. */

export interface Series {
  key: string
  label: string
  color: string // a CSS var() reference
}

interface Tip {
  x: number
  y: number
  content: ReactNode
}

function useTip() {
  const ref = useRef<HTMLDivElement>(null)
  const [tip, setTip] = useState<Tip | null>(null)
  const show = (e: { clientX: number; clientY: number }, content: ReactNode) => {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return
    // keep the tooltip inside the chart: flip to the left of the cursor near the right edge
    const x = e.clientX - box.left
    setTip({ x: x + 212 > box.width ? Math.max(0, x - 212) : x + 12, y: Math.max(e.clientY - box.top - 12, 0), content })
  }
  const node = tip && (
    <div className="viz-tip" role="tooltip" style={{ left: tip.x, top: tip.y }}>{tip.content}</div>
  )
  return { ref, show, hide: () => setTip(null), node }
}

export function Legend({ series, extra }: { series: Series[]; extra?: ReactNode }) {
  return (
    <div className="viz-legend">
      {series.map((s) => (
        <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
      ))}
      {extra}
    </div>
  )
}

const niceMax = (v: number) => {
  if (v <= 5) return 5
  const p = 10 ** Math.floor(Math.log10(v))
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v) ?? v
}

/* ----------------------------------------------------------- stacked columns -- */

export interface ColumnDatum {
  id: number | string
  label: string // x label (short)
  title: string // tooltip heading
  values: Record<string, number>
  marker?: number // e.g. expected attendees, drawn as a tick
}

export function StackedColumns({ data, series, markerLabel, height = 220, onSelect }: {
  data: ColumnDatum[]
  series: Series[]
  markerLabel?: string
  height?: number
  onSelect?: (d: ColumnDatum) => void
}) {
  const { ref, show, hide, node } = useTip()
  const W = 720
  const pad = { l: 36, r: 8, t: 10, b: 40 }
  const plotH = height - pad.t - pad.b
  const max = niceMax(Math.max(1, ...data.map((d) => Math.max(
    series.reduce((s, x) => s + (d.values[x.key] ?? 0), 0), d.marker ?? 0))))
  const ticks = [0, max / 2, max]
  const slot = (W - pad.l - pad.r) / Math.max(data.length, 1)
  const barW = Math.max(6, Math.min(36, slot - 6))
  const y = (v: number) => pad.t + plotH - (v / max) * plotH
  const every = Math.ceil(data.length / 12) // thin out x labels when crowded

  return (
    <div className="viz" ref={ref} onMouseLeave={hide}>
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Attendance per event">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className={t === 0 ? 'viz-axis' : 'viz-grid'} />
            <text x={pad.l - 6} y={y(t) + 4} className="viz-tick" textAnchor="end">{Math.round(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const cx = pad.l + slot * i + slot / 2
          let acc = 0
          const total = series.reduce((s, x) => s + (d.values[x.key] ?? 0), 0)
          const segs = series.map((s, si) => {
            const v = d.values[s.key] ?? 0
            if (!v) return null
            const y0 = y(acc), y1 = y(acc + v)
            acc += v
            const top = series.slice(si + 1).every((n) => !(d.values[n.key] ?? 0))
            const h = Math.max(0, y0 - y1 - (top ? 0 : 2)) // 2px surface gap between segments
            return top
              ? <path key={s.key} d={roundedTop(cx - barW / 2, y1, barW, h, Math.min(4, barW / 2))} fill={s.color} />
              : <rect key={s.key} x={cx - barW / 2} y={y1 + 2} width={barW} height={h} fill={s.color} />
          })
          return (
            <g key={d.id} className={onSelect ? 'viz-hit clickable' : 'viz-hit'}
              onMouseMove={(e) => show(e, (
                <>
                  <strong>{d.title}</strong>
                  {series.map((s) => (
                    <div key={s.key}><i style={{ background: s.color }} />{s.label}<b>{d.values[s.key] ?? 0}</b></div>
                  ))}
                  <div className="viz-tip-total">Total<b>{total}</b></div>
                  {d.marker !== undefined && <div>{markerLabel}<b>{d.marker}</b></div>}
                  {d.marker ? <div>Turnout<b>{Math.round((total / d.marker) * 100)}%</b></div> : null}
                </>
              ))}
              onClick={() => onSelect?.(d)}>
              <rect x={pad.l + slot * i} y={pad.t} width={slot} height={plotH} fill="transparent" />
              {segs}
              {d.marker !== undefined && d.marker > 0 && (
                <line x1={cx - barW / 2 - 4} x2={cx + barW / 2 + 4} y1={y(d.marker)} y2={y(d.marker)} className="viz-marker" />
              )}
              {i % every === 0 && (
                <text x={cx} y={height - pad.b + 16} className="viz-tick" textAnchor="middle">{d.label}</text>
              )}
            </g>
          )
        })}
      </svg>
      {node}
    </div>
  )
}

function roundedTop(x: number, y: number, w: number, h: number, r: number) {
  if (h <= r) return `M${x},${y + h}V${y}H${x + w}V${y + h}Z`
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

/* ------------------------------------------------------------------ lines -- */

export interface LinePoint {
  label: string // x tick
  title: string // tooltip heading
  values: Record<string, number>
}

/** Multi-series line chart with a crosshair tooltip (change over time). */
export function LineChart({ data, series, height = 220, extraTip }: {
  data: LinePoint[]
  series: Series[]
  height?: number
  extraTip?: (d: LinePoint) => ReactNode
}) {
  const { ref, show, hide, node } = useTip()
  const [hover, setHover] = useState<number | null>(null)
  const W = 720
  const pad = { l: 36, r: 12, t: 12, b: 32 }
  const plotW = W - pad.l - pad.r
  const plotH = height - pad.t - pad.b
  const max = niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => d.values[s.key] ?? 0))))
  const x = (i: number) => pad.l + (data.length <= 1 ? plotW / 2 : (i / (data.length - 1)) * plotW)
  const y = (v: number) => pad.t + plotH - (v / max) * plotH
  const every = Math.ceil(data.length / 8)
  const step = data.length <= 1 ? plotW : plotW / (data.length - 1)

  return (
    <div className="viz" ref={ref} onMouseLeave={() => { hide(); setHover(null) }}>
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Attendance over time">
        {[0, max / 2, max].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className={t === 0 ? 'viz-axis' : 'viz-grid'} />
            <text x={pad.l - 6} y={y(t) + 4} className="viz-tick" textAnchor="end">{Math.round(t)}</text>
          </g>
        ))}
        {data.map((d, i) => i % every === 0 && (
          <text key={i} x={x(i)} y={height - 10} className="viz-tick" textAnchor="middle">{d.label}</text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + plotH} className="viz-crosshair" />}
        {series.map((s) => (
          <g key={s.key}>
            <polyline fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
              points={data.map((d, i) => `${x(i)},${y(d.values[s.key] ?? 0)}`).join(' ')} />
            {(data.length <= 24 || hover !== null) && data.map((d, i) => (data.length <= 24 || i === hover) && (
              <circle key={i} cx={x(i)} cy={y(d.values[s.key] ?? 0)} r={i === hover ? 5 : 3}
                fill={s.color} className="viz-dot" />
            ))}
          </g>
        ))}
        {data.map((d, i) => (
          <rect key={i} x={x(i) - step / 2} y={pad.t} width={step} height={plotH} fill="transparent"
            onMouseMove={(e) => {
              setHover(i)
              show(e, (
                <>
                  <strong>{d.title}</strong>
                  {series.map((s) => (
                    <div key={s.key}><i style={{ background: s.color }} />{s.label}<b>{d.values[s.key] ?? 0}</b></div>
                  ))}
                  {extraTip?.(d)}
                </>
              ))
            }} />
        ))}
      </svg>
      {node}
    </div>
  )
}

/* ---------------------------------------------------------------- rate bars -- */

/** Horizontal bars of a 0..1 rate with "attended / expected" beside it. */
export function RateBars({ data, threshold, onSelect }: {
  data: { id: number | string; label: string; rate: number; attended: number; expected: number }[]
  threshold?: number // rates below get a warning mark (icon + text, never color alone)
  onSelect?: (id: number | string) => void
}) {
  return (
    <div className="hbars">
      {data.map((d) => {
        const low = threshold !== undefined && d.rate < threshold
        return (
          <button key={d.id} type="button" className="hbar rate" onClick={() => onSelect?.(d.id)} disabled={!onSelect}
            title={`${d.label}: ${Math.round(d.rate * 100)}% (${d.attended} of ${d.expected})`}>
            <span className="hbar-label">{low && <span className="risk" aria-label="below threshold">⚠ </span>}{d.label}</span>
            <span className="hbar-track rate-track">
              <span className="hbar-fill" style={{ width: `${d.rate * 100}%`, background: 'var(--series-1)' }} />
            </span>
            <span className="hbar-value"><b>{Math.round(d.rate * 100)}%</b> <span className="muted">{d.attended}/{d.expected}</span></span>
          </button>
        )
      })}
    </div>
  )
}

/* -------------------------------------------------------------- horizontal bars -- */

export function HBars({ data, color = 'var(--series-1)', unit = '', onSelect }: {
  data: { id: number | string; label: string; value: number }[]
  color?: string
  unit?: string
  onSelect?: (id: number | string) => void
}) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <div className="hbars">
      {data.map((d) => (
        <button key={d.id} type="button" className="hbar" onClick={() => onSelect?.(d.id)} disabled={!onSelect}
          title={`${d.label}: ${d.value}${unit}`}>
          <span className="hbar-label">{d.label}</span>
          <span className="hbar-track">
            <span className="hbar-fill" style={{ width: `${(d.value / max) * 100}%`, background: color }} />
          </span>
          <span className="hbar-value">{d.value}{unit}</span>
        </button>
      ))}
    </div>
  )
}

/* -------------------------------------------------------- part-to-whole strip -- */

export function ShareStrip({ parts }: {
  parts: { key: string; label: string; value: number; color: string; icon: string }[]
}) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1
  const shown = parts.filter((p) => p.value > 0)
  return (
    <div>
      <div className="strip" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(', ')}>
        {shown.map((p) => (
          <span key={p.key} style={{ flexGrow: p.value, background: p.color }} title={`${p.label}: ${p.value}`} />
        ))}
      </div>
      <div className="viz-legend">
        {parts.map((p) => (
          <span key={p.key}>
            <i style={{ background: p.color }} />{p.icon} {p.label}
            <b>{p.value}</b><span className="muted">({Math.round((p.value / total) * 100)}%)</span>
          </span>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- chart card -- */

export function ChartCard({ title, subtitle, table, children, legend }: {
  title: string
  subtitle?: string
  table: { head: string[]; rows: (string | number)[][] }
  children: ReactNode
  legend?: ReactNode
}) {
  const [asTable, setAsTable] = useState(false)
  const id = useMemo(() => Math.random().toString(36).slice(2), [])
  return (
    <section className="card chart-card" aria-labelledby={id}>
      <header>
        <div>
          <h4 id={id}>{title}</h4>
          {subtitle && <div className="small muted">{subtitle}</div>}
        </div>
        <button className="link small" onClick={() => setAsTable(!asTable)}>{asTable ? 'Chart' : 'Table'}</button>
      </header>
      {asTable ? (
        <div className="table-wrap viz-table">
          <table>
            <thead><tr>{table.head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : (
        <>
          {legend}
          {children}
        </>
      )}
    </section>
  )
}
