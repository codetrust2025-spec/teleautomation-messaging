import React, { useMemo } from 'react'
import { formatCountdown } from '../utils/accountUi.js'
import { buildFleetHealthRows } from '../utils/fleetHealth.js'
import { formatLogTime } from '../utils/accountUi.js'
import {
  buildDeskPerformanceSeries,
  chartAreaPath,
  chartPathFromValues,
} from '../utils/deskPerformanceSeries.js'

export function DeskDonut({ value, max = 100, color = '#22c55e', label, sublabel }) {
  const deg = (max > 0 ? Math.min(1, value / max) : 0) * 360
  return (
    <div className="desk-donut" style={{ '--donut-color': color, '--donut-deg': `${deg}deg` }}>
      <div className="desk-donut__ring" aria-hidden>
        <div className="desk-donut__hole">
          <span className="desk-donut__value">{sublabel === '%' ? `${Math.round(value)}%` : value}</span>
        </div>
      </div>
      <span className="desk-donut__label">{label}</span>
      {sublabel && <span className="desk-donut__sub">{sublabel}</span>}
    </div>
  )
}

export function DeskPerformanceChart({
  dailyStats,
  logs = [],
  modeFilter = 'all',
  statsWindowLabel = 'Last 24 hours',
}) {
  const series = useMemo(
    () => buildDeskPerformanceSeries({ dailyStats, logs, modeFilter }),
    [dailyStats, logs, modeFilter],
  )

  const width = 400
  const height = 120
  const padX = 8
  const padY = 10
  const chartH = height - 22

  const maxSent = Math.max(...series.sent, 1)
  const sentLine = chartPathFromValues(series.sent, width, chartH, padX, padY, maxSent)
  const sentArea = chartAreaPath(series.sent, width, chartH, padX, padY, maxSent)

  const rateValues = series.successRate.map(v => (v == null ? 0 : v))
  const rateLine = chartPathFromValues(rateValues, width, chartH, padX, padY, 100)

  const failedMax = Math.max(...series.failed, 1)
  const failedLine = chartPathFromValues(series.failed, width, chartH, padX, padY, failedMax)

  const step = (width - padX * 2) / Math.max(series.sent.length - 1, 1)

  return (
    <div className="desk-perf-chart">
      <div className="desk-perf-chart__legend">
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--green" />Posts sent (hourly)</span>
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--red" />Failed (logs)</span>
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--purple" />Success rate</span>
      </div>
      {!series.hasData && (
        <p className="desk-perf-chart__empty">No sends recorded in this window yet.</p>
      )}
      <svg
        className="desk-perf-chart__svg"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Performance ${statsWindowLabel}: ${series.totalSent} posts sent`}
      >
        <defs>
          <linearGradient id="deskAreaGreen" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 6, 12, 18, 23].map(i => {
          const x = padX + i * step
          return (
            <line
              key={i}
              x1={x}
              y1={padY}
              x2={x}
              y2={chartH - 2}
              stroke="#1e293b"
              strokeWidth="1"
            />
          )
        })}
        <path d={sentArea} fill="url(#deskAreaGreen)" />
        <polyline points={sentLine} fill="none" stroke="#4ade80" strokeWidth="2" />
        <polyline points={failedLine} fill="none" stroke="#f87171" strokeWidth="1.5" opacity="0.85" />
        <polyline points={rateLine} fill="none" stroke="#a78bfa" strokeWidth="1.75" strokeDasharray="4 3" />
        {series.labels.map((label, i) => {
          if (!label) return null
          const x = padX + i * step
          return (
            <text
              key={`${label}-${i}`}
              x={x}
              y={height - 4}
              fill="#64748b"
              fontSize="8"
              textAnchor="middle"
            >
              {label}
            </text>
          )
        })}
      </svg>
      <p className="desk-perf-chart__foot">
        {series.totalSent} sent
        {series.totalFailed > 0 ? ` · ${series.totalFailed} failed (from logs)` : ''}
        {series.usesBackendHistory ? ' · from send history' : ' · from live logs'}
      </p>
    </div>
  )
}

function logLineText(entry) {
  return (entry.summary || entry.fields?.detail || entry.msg || '').trim()
}

function logIcon(level, text) {
  const lvl = (level || '').toLowerCase()
  const lower = text.toLowerCase()
  if (lvl === 'error' || lower.includes('fail') || lower.includes('rate limit')) return '⚠'
  if (lower.includes('forward') || lower.includes('sent')) return '↻'
  if (lower.includes('sleep') || lower.includes('wait')) return '⏱'
  if (lvl === 'warn') return '⚠'
  return '●'
}

function agoLabel(ts) {
  if (!ts) return 'just now'
  const t = Date.parse(ts)
  if (!Number.isFinite(t)) return 'just now'
  const sec = Math.floor((Date.now() - t) / 1000)
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

export function buildRecentActivity(logs, accountInfo, limit = 10) {
  const rows = []
  for (const entry of logs || []) {
    const text = logLineText(entry)
    if (!text) continue
    const slot = entry.account_id
    const info = accountInfo?.[slot]
    const meta = (info?.first_name || info?.username || slot || 'System')
    rows.push({
      id: `${slot}-${entry.timestamp || entry.time}-${rows.length}`,
      icon: logIcon(entry.level, text),
      title: text.length > 72 ? `${text.slice(0, 72)}…` : text,
      meta,
      ago: agoLabel(entry.timestamp || entry.time),
    })
    if (rows.length >= limit) break
  }
  return rows
}

export function buildDeskAlerts({ healthRows, failedCount, alertCount }) {
  const items = []
  for (const row of healthRows || []) {
    if (!row.attention || !row.attentionHint) continue
    items.push({
      id: `health-${row.slot}`,
      type: row.attention === 'critical' ? 'error' : 'warn',
      title: row.attentionHint,
      meta: row.displayName || row.slot,
      ago: 'now',
    })
    if (items.length >= 6) break
  }
  if (failedCount > 0 && items.length < 8) {
    items.unshift({
      id: 'failed-tick',
      type: 'error',
      title: `${failedCount} failed send${failedCount === 1 ? '' : 's'} this tick`,
      meta: 'Forwarding',
      ago: 'now',
    })
  }
  if (alertCount > 0 && items.length < 8) {
    items.push({
      id: 'alerts-summary',
      type: 'warn',
      title: `${alertCount} account${alertCount === 1 ? '' : 's'} need attention`,
      meta: 'Fleet health',
      ago: 'now',
    })
  }
  return items.slice(0, 8)
}

export function DeskKpiBar({ color, variant = 'line' }) {
  return (
    <div className={`desk-stat-card__bar desk-stat-card__bar--${variant}`}>
      <div className="desk-stat-card__bar-fill" style={{ background: color, width: variant === 'bars' ? '70%' : '55%' }} />
    </div>
  )
}

export { formatCountdown, buildFleetHealthRows }
