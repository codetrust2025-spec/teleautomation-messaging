import React from 'react'
import { MetricBlock, MetricGrid } from './ui/MetricBlock.jsx'

/**
 * Progress stats with plain labels so users understand each number.
 */
export function ProgressStatsPanel({
  title,
  subtitle,
  helpText,
  totalGroups,
  success,
  failed,
  successRate,
  processed,
  secondary,
  children,
  hideGrid = false,
  successLabel = 'Posted OK',
  failedLabel = 'Failed',
  successRateLabel = 'Success rate',
  processedHint = 'tried this cycle',
  groupsLabel = 'Groups in list',
  successTitle = 'Messages posted successfully this cycle',
  failedTitle = 'Groups where posting failed this cycle',
  rateTitle = 'Share of attempts that succeeded (posted OK ÷ tried)',
}) {
  const rateDisplay = successRate == null || successRate === '—'
    ? '—'
    : `${successRate}%`
  const rateNum = rateDisplay === '—' ? NaN : parseFloat(successRate)
  const rateTone = !Number.isFinite(rateNum)
    ? 'neutral'
    : rateNum >= 70
      ? 'good'
      : rateNum >= 40
        ? 'warn'
        : 'bad'

  return (
    <section className="progress-stats-panel">
      <header className="progress-stats-panel-header">
        {title && <h3 className="progress-stats-panel-title">{title}</h3>}
        {subtitle && <p className="progress-stats-panel-subtitle">{subtitle}</p>}
      </header>
      {helpText && <p className="progress-stats-help">{helpText}</p>}

      {!hideGrid && (
      <MetricGrid columns={4} className="progress-stats-grid">
        <MetricBlock label={groupsLabel} value={totalGroups} title="Groups in this account's list" />
        <MetricBlock label={successLabel} value={success} tone="success" title={successTitle} />
        <MetricBlock label={failedLabel} value={failed} tone="danger" title={failedTitle} />
        <MetricBlock
          label={successRateLabel}
          value={rateDisplay}
          sub={processed != null ? `${processed} ${processedHint}` : null}
          tone={rateTone}
          title={rateTitle}
        />
      </MetricGrid>
      )}

      {secondary && (
        <div className="progress-stats-secondary" role="list" aria-label="Extra stats">
          {secondary}
        </div>
      )}

      {children}
    </section>
  )
}

/** Readable chip for secondary row */
export function ProgressStatChip({ label, value, warn, title, icon, helper }) {
  return (
    <span
      className={`progress-stats-chip${warn ? ' progress-stats-chip--warn' : ''}${helper ? ' progress-stats-chip--explained' : ''}`}
      role="listitem"
      title={title}
    >
      <span className="progress-stats-chip-label">
        {icon && <span className="progress-stats-chip-icon" aria-hidden>{icon}</span>}
        {label}
      </span>
      <strong>{value}</strong>
      {helper && <span className="progress-stats-chip-helper">{helper}</span>}
    </span>
  )
}
