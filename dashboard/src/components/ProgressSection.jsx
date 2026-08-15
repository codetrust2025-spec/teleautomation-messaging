import React from 'react'
import { ProgressBar } from './ui/ProgressBar.jsx'
import { StatusBadge } from './StatusBadge.jsx'
import { formatCountdown, isHeavyRateLimit } from '../utils/accountUi'

export function ProgressSection({
  activeAcctState,
  displayCurrentGroup,
  countdown,
  cycleElapsed,
  progressValue,
  progressMax,
  hasCycleRun,
  deepDive = false,
}) {
  const heavyLimit = isHeavyRateLimit(activeAcctState)
  const running = activeAcctState?.running && !heavyLimit
  const status = heavyLimit
    ? 'sleeping'
    : activeAcctState?.status === 'flood_wait'
      ? 'rate_limited'
      : running
        ? 'running'
        : 'stopped'

  let actionLabel = 'Idle'
  let actionDetail = null
  if (running && displayCurrentGroup) {
    actionLabel = 'Sending'
    actionDetail = displayCurrentGroup
  } else if (countdown > 0) {
    actionLabel = heavyLimit ? 'Sleeping' : 'Waiting'
    actionDetail = formatCountdown(countdown)
  } else if (running) {
    actionLabel = 'Running'
  }

  const plainSummary = (() => {
    if (heavyLimit) {
      return countdown > 0
        ? `Telegram rate limit — this account is resting. Resumes in about ${actionDetail}.`
        : 'Telegram rate limit — this account is resting until the limit clears.'
    }
    if (running && displayCurrentGroup) {
      return `Sending your message to @${displayCurrentGroup.replace(/^@/, '')} right now.`
    }
    if (countdown > 0) {
      return `Paused between groups. Next action in about ${actionDetail}.`
    }
    if (running) {
      return 'Worker is running through your group list.'
    }
    return 'Worker is stopped — use Start on the account card to begin.'
  })()

  return (
    <div className={`progress-panel${deepDive ? ' progress-panel--deep-dive' : ''}`}>
      {!deepDive && (
        <p className="progress-plain-summary">{plainSummary}</p>
      )}
      {heavyLimit && (
        <div className="priority-banner priority-banner--sleep" role="alert">
          <span className="priority-banner-icon">⏸</span>
          <div>
            <strong>Rate limited — account sleeping</strong>
            <p>{activeAcctState?.notification || 'Heavy rate limit active. Worker will resume automatically.'}</p>
          </div>
          {countdown > 0 && (
            <span className="priority-banner-timer">{formatCountdown(countdown)}</span>
          )}
        </div>
      )}
      {deepDive && displayCurrentGroup && running && (
        <p className="progress-deep-target">
          Current target: <strong>@{displayCurrentGroup.replace(/^@/, '')}</strong>
        </p>
      )}
      {!deepDive && (
      <div className="progress-panel-top">
        <div className="progress-action">
          <StatusBadge status={status} countdown={countdown} pulse={running} large />
          <div className="progress-action-text">
            <span className={`live-indicator${running ? ' live-indicator--on' : ''}`}>
              {actionLabel}
            </span>
            {actionDetail && (
              <span className="progress-action-detail">
                {actionLabel === 'Sending' ? `→ @${actionDetail}` : actionDetail}
              </span>
            )}
          </div>
        </div>
        <div className="progress-meta">
          {cycleElapsed > 0 && running && (
            <span className="progress-elapsed" title="Time in current cycle">
              Cycle time {Math.floor(cycleElapsed / 60)}m {String(cycleElapsed % 60).padStart(2, '0')}s
            </span>
          )}
          <span className="progress-count">
            <span className="progress-count-label">Groups this cycle</span>
            <span className="progress-count-value">
              {hasCycleRun ? progressValue : 0} / {progressMax}
            </span>
          </span>
        </div>
      </div>
      )}
      {deepDive && cycleElapsed > 0 && running && (
        <p className="progress-deep-elapsed">
          Cycle time {Math.floor(cycleElapsed / 60)}m {String(cycleElapsed % 60).padStart(2, '0')}s
        </p>
      )}
      <ProgressBar
        value={hasCycleRun ? progressValue : 0}
        max={progressMax}
        label={`Groups processed this cycle: ${hasCycleRun ? progressValue : 0} of ${progressMax}`}
        large
      />
    </div>
  )
}
