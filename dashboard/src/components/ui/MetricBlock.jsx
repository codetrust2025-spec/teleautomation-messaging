import React from 'react'

const TONE_CLASS = {
  neutral: '',
  success: 'metric-block--success',
  good: 'metric-block--success',
  warning: 'metric-block--warning',
  warn: 'metric-block--warning',
  danger: 'metric-block--danger',
  bad: 'metric-block--danger',
}

export function MetricBlock({
  label,
  value,
  sub,
  title,
  /** Longer explanation; shows a ? icon with hover/focus tooltip */
  help,
  tone = 'neutral',
  density = 'compact',
  variant = 'card',
  progress,
  className = '',
  /** Primary KPI — stronger border/glow in daily stats */
  highlight = false,
  highlightVariant,
}) {
  const hasProgress = progress != null && !Number.isNaN(Number(progress))
  const pct = hasProgress ? Math.max(0, Math.min(100, Number(progress))) : 0
  const classes = [
    'metric-block',
    `metric-block--${density}`,
    `metric-block--${variant}`,
    TONE_CLASS[tone] || '',
    highlight ? 'metric-block--key' : '',
    highlight && highlightVariant ? `metric-block--key-${highlightVariant}` : '',
    className,
  ].filter(Boolean).join(' ')

  const tip = help || title

  return (
    <div className={classes} title={tip || undefined}>
      <div className="metric-block-head">
        <span className="metric-block-label-row">
          <span className="metric-block-label">{label}</span>
          {help ? (
            <button
              type="button"
              className="metric-block-help"
              aria-label={`About ${label}`}
              title={help}
              onClick={(e) => e.stopPropagation()}
            >
              ?
            </button>
          ) : null}
        </span>
        <span className="metric-block-value">{value}</span>
      </div>
      {sub && <span className="metric-block-sub">{sub}</span>}
      {hasProgress && (
        <div className="metric-block-progress" aria-hidden>
          <div className="metric-block-progress-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}

export function MetricGrid({ columns = 2, auto = false, className = '', children }) {
  const classes = [
    'metric-grid',
    auto ? 'metric-grid--auto' : `metric-grid--${columns}`,
    className,
  ].filter(Boolean).join(' ')

  return <div className={classes}>{children}</div>
}
