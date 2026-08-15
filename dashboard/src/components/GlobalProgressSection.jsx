import React from 'react'
import { ProgressBar } from './ui/ProgressBar.jsx'
import { StatusBadge } from './StatusBadge.jsx'
import { AccountPerformanceChart } from './AccountPerformanceChart.jsx'
import { FleetHealthPanel } from './FleetHealthPanel.jsx'
import { accountLabel, formatCountdown } from '../utils/accountUi'
import { SABHI_ACCOUNTS, SABHI_ACCOUNTS_COMBINED } from '../utils/sabAccountsUi.js'

const DEFAULT_SECTIONS = {
  summary: true,
  sleepBanner: true,
  progressTop: true,
  progressBar: true,
  fleetHealth: true,
  performance: true,
  legend: true,
  chips: true,
}

export function FleetAccountChips({ perAccount, subscriptionSlots = [], compact = false }) {
  const subs = Array.isArray(subscriptionSlots) ? subscriptionSlots : []
  if (!perAccount?.length) return null

  return (
    <>
      {!compact && (
      <p className="fleet-chips-legend">
        Each box is one account. Dot color = status (green running, yellow sleeping).
        {' '}<span className="legend-sub">◆</span> = subscription account.
      </p>
      )}
      {compact && (
        <p className="fleet-chips-legend fleet-chips-legend--compact">
          Status only — see <strong>Overview</strong> for OK/Fail totals and <strong>Selected</strong> for per-account cycle detail.
        </p>
      )}
      <div className={`fleet-account-chips${compact ? ' fleet-account-chips--compact' : ''}`} aria-label="Per-account status">
        {perAccount.map((row) => {
          const isSub = subs.includes(row.slot)
          return (
            <span
              key={row.slot}
              className={`fleet-chip fleet-chip--${row.status}${isSub ? ' fleet-chip--subscription' : ''}${compact ? ' fleet-chip--compact' : ''}`}
              title={compact
                ? `${accountLabel(row.slot)} — ${row.status}`
                : `${accountLabel(row.slot)}${isSub ? ' · ◆ Subscription' : ''} — ${row.status}. Posted OK: ${row.success}, Failed: ${row.failed}`}
            >
              {isSub && <span className="fleet-chip-sub-mark" aria-hidden>◆</span>}
              <span className="fleet-chip-dot" aria-hidden />
              <span className="fleet-chip-name">
                {accountLabel(row.slot).replace('Account ', 'A')}
              </span>
              {!compact && (
              <span className="fleet-chip-stats">
                <span className="fleet-chip-stat fleet-chip-stat--ok">OK {row.success}</span>
                <span className="fleet-chip-stat fleet-chip-stat--fail">Fail {row.failed}</span>
              </span>
              )}
            </span>
          )
        })}
      </div>
    </>
  )
}

export function GlobalProgressSection({
  fleet,
  countdown,
  accountInfo,
  statsWindow,
  dailyStats,
  subscriptionSlots = [],
  sections: sectionsProp,
}) {
  const sections = { ...DEFAULT_SECTIONS, ...sectionsProp }
  const subs = Array.isArray(subscriptionSlots) ? subscriptionSlots : []
  const {
    runningCount,
    sleepingCount,
    rateLimitedCount,
    idleCount,
    sending,
    hasAnyCycle,
    progressValue,
    progressMax,
    accountCount,
  } = fleet

  let status = 'stopped'
  if (runningCount > 0) status = 'running'
  else if (sleepingCount > 0) status = 'sleeping'
  else if (rateLimitedCount > 0) status = 'rate_limited'

  const pulse = runningCount > 0

  let actionLabel = 'Idle'
  let actionDetail = null

  if (sending.length > 0) {
    actionLabel = sending.length === 1 ? 'Sending' : `${sending.length} sending`
    actionDetail =
      sending.length === 1
        ? sending[0].group
        : sending.map((s) => accountLabel(s.slot).replace('Account ', 'A')).join(', ')
  } else if (countdown > 0 && runningCount + sleepingCount + rateLimitedCount > 0) {
    actionLabel = sleepingCount > 0 && runningCount === 0 ? 'Sleeping' : 'Waiting'
    actionDetail = formatCountdown(countdown)
  } else if (runningCount > 0) {
    actionLabel = `${runningCount} running`
  } else if (sleepingCount > 0) {
    actionLabel = `${sleepingCount} sleeping`
  }

  const statusParts = []
  if (runningCount) statusParts.push(`${runningCount} run`)
  if (sleepingCount) statusParts.push(`${sleepingCount} sleep`)
  if (rateLimitedCount) statusParts.push(`${rateLimitedCount} limited`)
  if (idleCount) statusParts.push(`${idleCount} idle`)

  const plainSummary = (() => {
    if (sending.length > 0) {
      return `${sending.length} account${sending.length !== 1 ? 's are' : ' is'} posting to a group right now.`
    }
    if (runningCount > 0 && countdown > 0) {
      return `${runningCount} account${runningCount !== 1 ? 's' : ''} running — waiting between posts (~${formatCountdown(countdown)}).`
    }
    if (runningCount > 0) {
      return `${runningCount} account${runningCount !== 1 ? 's are' : ' is'} actively forwarding.`
    }
    if (sleepingCount > 0) {
      return `${sleepingCount} account${sleepingCount !== 1 ? 's are' : ' is'} paused (rate limit or cooldown).`
    }
    return 'No accounts are sending right now. Start workers from the account cards on the left.'
  })()

  return (
    <div className="progress-panel progress-panel--global">
      {sections.summary && (
        <p className="progress-plain-summary">{plainSummary}</p>
      )}
      {sections.sleepBanner && sleepingCount > 0 && runningCount === 0 && (
        <div className="priority-banner priority-banner--sleep priority-banner--compact" role="status">
          <span className="priority-banner-icon">⏸</span>
          <div>
            <strong>{sleepingCount} account{sleepingCount !== 1 ? 's' : ''} rate-limited</strong>
            {countdown > 0 && (
              <p>Earliest resume ~{formatCountdown(countdown)}</p>
            )}
          </div>
        </div>
      )}

      {sections.progressTop && (
      <div className="progress-panel-top">
        <div className="progress-action">
          <StatusBadge status={status} countdown={countdown} pulse={pulse} large />
          <div className="progress-action-text">
            <span className={`live-indicator${pulse ? ' live-indicator--on' : ''}`}>
              {actionLabel}
            </span>
            {actionDetail && (
              <span className="progress-action-detail">
                {sending.length === 1 && actionLabel === 'Sending'
                  ? `→ @${actionDetail}`
                  : actionDetail}
              </span>
            )}
            {statusParts.length > 0 && (
              <span className="progress-fleet-summary">{statusParts.join(' · ')}</span>
            )}
          </div>
        </div>
        <div className="progress-meta">
          <span className="progress-meta-note" title="Configured worker slots">
            {accountCount} accounts total
          </span>
          <span className="progress-count">
            <span className="progress-count-label">{SABHI_ACCOUNTS_COMBINED}</span>
            <span className="progress-count-value">
              {hasAnyCycle ? progressValue : 0} / {progressMax}
            </span>
          </span>
        </div>
      </div>
      )}

      {sections.progressBar && (
      <ProgressBar
        value={hasAnyCycle ? progressValue : 0}
        max={progressMax}
        label={`${SABHI_ACCOUNTS} — groups processed this cycle: ${hasAnyCycle ? progressValue : 0} of ${progressMax}`}
      />
      )}

      {sections.fleetHealth && fleet.perAccount.length > 0 && (
        <FleetHealthPanel
          perAccount={fleet.perAccount}
          accountInfo={accountInfo}
          statsWindow={statsWindow}
          dailyStats={dailyStats}
        />
      )}

      {sections.performance && fleet.perAccount.length > 0 && (
        <AccountPerformanceChart
          perAccount={fleet.perAccount}
          accountInfo={accountInfo}
          statsWindow={statsWindow}
          subscriptionSlots={subs}
        />
      )}

      {sections.chips && fleet.perAccount.length > 0 && (
        <FleetAccountChips perAccount={fleet.perAccount} subscriptionSlots={subs} />
      )}
    </div>
  )
}
