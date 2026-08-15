import React from 'react'

const TONE_CLASS = {
  success: 'metric-block--success',
  good: 'metric-block--success',
  warning: 'metric-block--warning',
  warn: 'metric-block--warning',
  danger: 'metric-block--danger',
  bad: 'metric-block--danger',
  neutral: '',
}

export function ProgressBar({ value = 0, max = 100, label, tone = 'neutral', size = 'sm', large = false, className = '' }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, Math.round((Number(value) / Number(max)) * 100))) : 0
  return (
    <div className={['metric-block', `progress-bar--${large ? 'md' : size}`, TONE_CLASS[tone] || '', className].filter(Boolean).join(' ')}>
      {(label || size !== 'micro') && (
        <div className="metric-block-head">
          <span className="metric-block-label">{label || 'Progress'}</span>
          <span className="metric-block-value">{pct}%</span>
        </div>
      )}
      <div className="metric-block-progress" aria-label={label ? `${label}: ${pct}%` : `${pct}%`}>
        <div className="metric-block-progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
