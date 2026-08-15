import React from 'react'
import { formatCountdown } from '../utils/accountUi'

const STATUS_CONFIG = {
  running: { label: 'Running', className: 'status-badge--running', icon: '●' },
  waiting: { label: 'Waiting', className: 'status-badge--waiting', icon: '●' },
  sleeping: { label: 'Waiting', className: 'status-badge--waiting', icon: '●' },
  flood: { label: 'Flood', className: 'status-badge--error', icon: '●' },
  error: { label: 'Error', className: 'status-badge--error', icon: '●' },
  rate_limited: { label: 'Flood', className: 'status-badge--error', icon: '●' },
  stopped: { label: 'Stopped', className: 'status-badge--stopped', icon: '●' },
  idle: { label: 'Not logged in', className: 'status-badge--idle', icon: '●' },
}

function supportsTimer(status) {
  return ['waiting', 'sleeping', 'running', 'rate_limited', 'flood'].includes(status)
}

export function StatusBadge({ status, countdown, timer, pulse, large, label }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.stopped
  const displayLabel = label || cfg.label
  const timerText = timer || (countdown > 0 ? formatCountdown(countdown) : null)
  return (
    <span
      className={`status-badge ${cfg.className}${pulse ? ' status-badge--pulse' : ''}${large ? ' status-badge--lg' : ''}`}
      title={timerText ? `${displayLabel} · next in ${timerText}` : displayLabel}
    >
      <span className="status-badge-icon" aria-hidden>{cfg.icon}</span>
      {displayLabel}
      {timerText && supportsTimer(status) && (
        <span className="status-badge-countdown">{timerText}</span>
      )}
    </span>
  )
}

export function HealthIndicator({ level, score }) {
  const labels = { good: 'Healthy', warning: 'Caution', bad: 'At risk', unknown: 'Health' }
  const n = score != null && !Number.isNaN(Number(score)) ? Number(score) : null
  const showScore = n != null && n > 0 && level !== 'unknown'
  const title = showScore ? `Health score ${Math.round(n)}%` : labels[level]
  return (
    <span className={`health-pill health-pill--${level}`} title={title}>
      <span className="health-pill-dot" aria-hidden />
      <span className="health-pill-text">{labels[level]}</span>
      {showScore && <span className="health-pill-score">{Math.round(n)}%</span>}
    </span>
  )
}
