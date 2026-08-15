import React, { useMemo } from 'react'
import { formatCountdown } from '../utils/accountUi.js'
import { buildFleetHealthRows } from '../utils/fleetHealth.js'
import { getDashboardModeConfig } from '../utils/workspaceDashboard.js'
import { MobSparkline } from '../mobile/MobSparkline.jsx'
import {
  accountRowsForDashboard,
  computeDashboardStats,
} from '../dashboard/dashboardStats.js'
import { DeskDonut } from './DeskDonut.jsx'
import { DeskPerformanceChart } from './DeskPerformanceChart.jsx'
import { buildDeskAlerts, buildLiveActivityFeed } from './deskFeedUtils.js'
import { formatSuccessRateDisplay } from '../utils/globalStats.js'

export function DesktopDashboardHome({
  state,
  loggedInSlots,
  postingModes,
  inboxUnreadTotal,
  fleet,
  globalCountdown,
  sentWindowLabel,
  activeSlot,
  activeRunning,
  anyProcessRunning = false,
  onSelectAccount,
  onOpenSetup,
  onOpenProgress,
  onResetReach,
  onStartAccount,
  onStopAccount,
  accountActionLoading,
  shutdownListCount,
  onNavBulk,
  onNavShutdown,
  onNavLogs,
  onNavData,
  onNavCandidates,
  onBookSlot,
  tickOverview,
  recentLogs,
  workspaceMode,
}) {
  const mode = getDashboardModeConfig(workspaceMode)

  const stats = useMemo(
    () =>
      computeDashboardStats({
        state,
        loggedInSlots,
        postingModes,
        inboxUnreadTotal,
        fleet,
        modeFilter: mode.modeFilter,
      }),
    [state, loggedInSlots, postingModes, inboxUnreadTotal, fleet, mode.modeFilter],
  )

  const accounts = useMemo(
    () => accountRowsForDashboard(state, loggedInSlots, postingModes, mode.modeFilter),
    [state, loggedInSlots, postingModes, mode.modeFilter],
  )

  const healthRows = useMemo(
    () =>
      buildFleetHealthRows(
        fleet.perAccount || [],
        state.account_info,
        state.daily_stats?.window,
        state.daily_stats?.reset_at ? new Date(state.daily_stats.reset_at).getTime() / 1000 : 0,
      ),
    [fleet.perAccount, state.account_info, state.daily_stats],
  )

  const activity = useMemo(
    () => buildLiveActivityFeed(recentLogs, state.account_info, 10),
    [recentLogs, state.account_info],
  )

  const alerts = useMemo(
    () =>
      buildDeskAlerts({
        healthRows,
        failedCount: fleet.failed ?? 0,
        alertCount: stats.alertCount,
      }),
    [healthRows, fleet.failed, stats.alertCount],
  )

  const progressPct = stats.progressMax > 0
    ? Math.round((stats.progressValue / stats.progressMax) * 100)
    : 0

  const tick = tickOverview || {}
  const postsSent = stats.postsToday ?? stats.messagesSent24h ?? 0
  const groupsTick = tick.groups ?? stats.progressMax
  const sentTick = tick.sent ?? stats.tickSent
  const failedTick = tick.failed ?? fleet.failed ?? 0
  const successTickRaw = tick.successRate ?? stats.successRate
  const successTickDisplay = formatSuccessRateDisplay(successTickRaw)
  const successTickNum = successTickRaw == null || successTickRaw === '—'
    ? NaN
    : Number(successTickRaw)
  const remainingTick = tick.remaining ?? Math.max(0, groupsTick - (stats.progressValue || 0))
  const skippedTick = tick.skipped ?? fleet.skippedAlreadyPosted ?? 0

  const accountTotal = mode.isFleet ? stats.totalAccounts : stats.modeEnabledCount
  const accountRunning = stats.displayRunning ?? stats.runningAccounts
  const accountResting = stats.displayResting ?? stats.restingAccounts
  const runningNow = mode.isCampaign ? stats.campRunning : stats.fwdRunning
  const fleetBusy =
    anyProcessRunning
    || accounts.some(row => row.running)
    || stats.sleeping
    || (Number(fleet?.runningCount) || 0) > 0
    || (Number(fleet?.sleepingCount) || 0) > 0
  const quickBusy = fleetBusy

  function kpiHighlight(key) {
    return mode.highlightKpi === key ? ' desk-kpi-card--highlight' : ''
  }

  return (
    <div className={`desk-dash desk-dash--sigma${mode.isCampaign ? ' desk-dash--campaign' : ''}${mode.isForwarding ? ' desk-dash--forwarding' : ''}`}>
      <div className="desk-kpi-row">
        <div className={`desk-kpi-card${kpiHighlight('accounts')}`}>
          <div className="desk-kpi-card__head">
            <span className="desk-kpi-card__icon" aria-hidden>👥</span>
            <span className="desk-kpi-card__label">Accounts</span>
          </div>
          <div className="desk-kpi-card__value desk-kpi-card__value--green">{accountTotal}</div>
          <div className="desk-kpi-card__sub">
            {accountRunning} running · {accountResting} resting
          </div>
          <MobSparkline color="#22c55e" />
        </div>
        <div className={`desk-kpi-card${kpiHighlight('forward')}`}>
          <div className="desk-kpi-card__head">
            <span className="desk-kpi-card__icon" aria-hidden>{mode.isCampaign ? '📣' : '✈'}</span>
            <span className="desk-kpi-card__label">{mode.postsKpiLabel}</span>
          </div>
          <div className="desk-kpi-card__value desk-kpi-card__value--blue">{postsSent}</div>
          <div className="desk-kpi-card__sub">{sentWindowLabel?.toLowerCase() || 'since reset'}</div>
          <MobSparkline color={mode.isCampaign ? '#f97316' : '#3b82f6'} />
        </div>
        <div className="desk-kpi-card">
          <div className="desk-kpi-card__head">
            <span className="desk-kpi-card__icon" aria-hidden>✉</span>
            <span className="desk-kpi-card__label">Inbox messages</span>
          </div>
          <div className="desk-kpi-card__value desk-kpi-card__value--purple">{stats.inboxNew}</div>
          <div className="desk-kpi-card__sub">
            {inboxUnreadTotal > 0 ? `${inboxUnreadTotal} unread` : 'New messages'}
          </div>
          <MobSparkline color="#8b5cf6" variant="bars" />
        </div>
        <div className={`desk-kpi-card${kpiHighlight('campaign')}`}>
          <div className="desk-kpi-card__head">
            <span className="desk-kpi-card__icon" aria-hidden>📣</span>
            <span className="desk-kpi-card__label">
              {mode.isCampaign ? 'Active campaigns' : 'Campaigns'}
            </span>
          </div>
          <div className="desk-kpi-card__value desk-kpi-card__value--orange">{stats.campRunning}</div>
          <div className="desk-kpi-card__sub">
            {mode.isCampaign ? 'accounts posting' : 'running'}
          </div>
          <MobSparkline color="#f97316" variant="flat" />
        </div>
        <div className="desk-kpi-card">
          <div className="desk-kpi-card__head">
            <span className="desk-kpi-card__icon" aria-hidden>✓</span>
            <span className="desk-kpi-card__label">Success rate</span>
          </div>
          <div className="desk-kpi-card__value desk-kpi-card__value--teal">
            {successTickDisplay === '—' ? '—' : `${successTickDisplay}%`}
          </div>
          <div className="desk-kpi-card__sub">this tick</div>
          <MobSparkline color="#14b8a6" />
        </div>
        <div className="desk-kpi-card desk-kpi-card--alert">
          <div className="desk-kpi-card__head">
            <span className="desk-kpi-card__icon" aria-hidden>⚠</span>
            <span className="desk-kpi-card__label">Alerts</span>
          </div>
          <div className="desk-kpi-card__value desk-kpi-card__value--red">{stats.alertCount}</div>
          <div className="desk-kpi-card__sub">Requires attention</div>
        </div>
      </div>

      <div className="desk-main-grid">
        <div className="desk-panel desk-panel--tall">
          <div className="desk-panel__head">
            <h2 className="desk-panel__title">{mode.performanceTitle}</h2>
            <span className="desk-panel__meta">Last 24 hours</span>
          </div>
          <DeskPerformanceChart
            postsSent={postsSent}
            tickSent={sentTick}
            successRate={Number.isFinite(successTickNum) ? successTickNum : 0}
          />
          {stats.sleeping && (
            <p className="desk-panel__hint">
              ⏱ Fleet sleeping {formatCountdown(globalCountdown || stats.countdown)}
            </p>
          )}
        </div>

        <div className="desk-panel desk-panel--tall">
          <div className="desk-panel__head">
            <h2 className="desk-panel__title">Live activity</h2>
            <button type="button" className="desk-panel__link" onClick={onNavLogs}>
              View logs
            </button>
          </div>
          <ul className="desk-activity-list">
            {activity.length === 0 && (
              <li className="desk-activity-item desk-activity-item--empty">No recent activity yet</li>
            )}
            {activity.map(item => (
              <li key={item.id} className="desk-activity-item">
                <span className="desk-activity-item__icon" aria-hidden>{item.icon}</span>
                <span className="desk-activity-item__body">
                  <span className="desk-activity-item__title">{item.title}</span>
                  <span className="desk-activity-item__meta">
                    {item.meta} · {item.ago}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="desk-panel desk-panel--tall">
          <div className="desk-panel__head">
            <h2 className="desk-panel__title">
              {mode.isCampaign ? 'Campaign accounts' : mode.isForwarding ? 'Forwarding accounts' : 'Accounts'}
            </h2>
            <button type="button" className="desk-panel__link" onClick={onOpenSetup}>
              Manage
            </button>
          </div>
          {accounts.length === 0 && (
            <p className="desk-panel__hint">
              No accounts have {mode.isCampaign ? 'campaign' : 'forwarding'} enabled. Open Manage to configure.
            </p>
          )}
          <div className="desk-accounts-scroll">
            {accounts.map(row => (
              <button
                key={row.slot}
                type="button"
                className="desk-account-row"
                onClick={() => onSelectAccount?.(row.slot)}
              >
                <span
                  className={`mob-account-row__dot mob-account-row__dot--${row.running ? 'on' : 'off'}`}
                  aria-hidden
                />
                <span
                  className="mob-account-row__avatar"
                  style={{ background: row.color }}
                  aria-hidden
                >
                  {row.initials}
                </span>
                <span className="mob-account-row__info">
                  <div className="mob-account-row__name">{row.displayName}</div>
                  <div className="mob-account-row__sub">{row.subLabel}</div>
                </span>
                <span
                  className={`mob-status-pill mob-status-pill--${row.pillClass || (row.running ? 'running' : 'rest')}`}
                >
                  {row.pillLabel}
                </span>
                <span className="mob-account-row__chev" aria-hidden>›</span>
              </button>
            ))}
          </div>
          <div className="mob-accounts-footer">
            <span>{accountTotal} in {mode.isCampaign ? 'campaign' : mode.isForwarding ? 'forwarding' : 'fleet'}</span>
            <span className="mob-accounts-footer__run">{accountRunning} Running</span>
            <span className="mob-accounts-footer__rest">{accountResting} Resting</span>
          </div>
        </div>
      </div>

      <div className="desk-bottom-grid">
        <div className="desk-panel">
          <div className="desk-panel__head">
            <h2 className="desk-panel__title">{mode.overviewTitle}</h2>
            <button type="button" className="desk-panel__link" onClick={onOpenProgress}>
              View all
            </button>
          </div>
          <div className="desk-donut-row">
            <DeskDonut value={groupsTick} max={groupsTick || 1} color="#60a5fa" label="Groups this tick" />
            <DeskDonut value={sentTick} max={groupsTick || 1} color="#22c55e" label="Sent this tick" />
            <DeskDonut value={failedTick} max={Math.max(groupsTick, failedTick, 1)} color="#ef4444" label="Failed" />
            <DeskDonut
              value={Number.isFinite(successTickNum) ? successTickNum : 0}
              max={100}
              color="#14b8a6"
              label="Success rate"
              sublabel={Number.isFinite(successTickNum) ? '%' : '—'}
            />
            <DeskDonut value={remainingTick} max={groupsTick || 1} color="#8b5cf6" label="Remaining" />
            <DeskDonut value={skippedTick} max={Math.max(groupsTick, skippedTick, 1)} color="#f97316" label="Skipped" />
          </div>
          <div className="mob-progress-bar desk-tick-bar" aria-hidden>
            <div
              className="mob-progress-bar__fill"
              style={{ width: `${Math.min(100, progressPct)}%` }}
            />
          </div>
          <p className="desk-tick-foot">
            {mode.tickFootLabel}: <strong>{stats.progressValue}</strong> / <strong>{stats.progressMax}</strong> groups
            <span className="desk-tick-foot__pct">{progressPct}%</span>
          </p>
          <div className="desk-panel__head" style={{ marginTop: 12 }}>
            <h3 className="desk-panel__subtitle">{mode.reachTitle}</h3>
            <button type="button" className="desk-panel__link" onClick={onResetReach}>
              Reset 24h
            </button>
          </div>
          <div className="desk-reach-metrics desk-reach-metrics--compact">
            <div>
              <div className="desk-overview__stat-label">{mode.postsTodayLabel}</div>
              <div className="desk-overview__stat-value" style={{ color: '#4ade80' }}>{postsSent}</div>
            </div>
            <div>
              <div className="desk-overview__stat-label">{mode.runningNowLabel}</div>
              <div className="desk-overview__stat-value" style={{ color: '#60a5fa' }}>{runningNow}</div>
            </div>
            <div>
              <div className="desk-overview__stat-label">Current sent</div>
              <div className="desk-overview__stat-value" style={{ color: '#fbbf24' }}>{sentTick}</div>
            </div>
            <div>
              <div className="desk-overview__stat-label">Success rate</div>
              <div className="desk-overview__stat-value" style={{ color: '#a78bfa' }}>
                {successTickDisplay === '—' ? '—' : `${successTickDisplay}%`}
              </div>
            </div>
          </div>
        </div>

        <div className="desk-panel">
          <h2 className="desk-panel__title">Quick actions</h2>
          <div className="desk-quick-sigma">
            {!quickBusy ? (
              <button
                type="button"
                className="desk-quick-btn desk-quick-btn--start desk-quick-btn--lg"
                disabled={!activeSlot || !!accountActionLoading}
                onClick={() => onStartAccount?.(activeSlot, false, mode.feature)}
              >
                {mode.startLabel}
              </button>
            ) : (
              <button
                type="button"
                className="desk-quick-btn desk-quick-btn--stop desk-quick-btn--lg"
                disabled={!activeSlot || !!accountActionLoading}
                onClick={() => onStopAccount?.(activeSlot, mode.feature)}
              >
                {mode.stopLabel}
              </button>
            )}
            <div className="desk-util-grid">
              <button type="button" className="desk-quick-btn desk-quick-btn--util" onClick={onNavBulk}>
                <span className="desk-quick-btn__ico" aria-hidden>☰</span>
                {mode.bulkLabel}
              </button>
              <button type="button" className="desk-quick-btn desk-quick-btn--util" onClick={onNavShutdown}>
                <span className="desk-quick-btn__ico desk-quick-btn__ico--red" aria-hidden>⏻</span>
                Shutdown{shutdownListCount > 0 ? ` (${shutdownListCount})` : ''}
              </button>
              <button type="button" className="desk-quick-btn desk-quick-btn--util" onClick={onNavLogs}>
                <span className="desk-quick-btn__ico desk-quick-btn__ico--purple" aria-hidden>📋</span>
                Logs
              </button>
              <button type="button" className="desk-quick-btn desk-quick-btn--util" onClick={onNavData}>
                <span className="desk-quick-btn__ico desk-quick-btn__ico--blue" aria-hidden>📊</span>
                Data
              </button>
              <button
                type="button"
                className="desk-quick-btn desk-quick-btn--util"
                onClick={onBookSlot}
              >
                <span className="desk-quick-btn__ico desk-quick-btn__ico--green" aria-hidden>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
                </span>
                Book slot
              </button>
            </div>
          </div>
        </div>

        <div className="desk-panel">
          <div className="desk-panel__head">
            <h2 className="desk-panel__title">Alerts &amp; notifications</h2>
            {stats.alertCount > 0 && (
              <span className="desk-panel__badge">{stats.alertCount}</span>
            )}
          </div>
          <ul className="desk-alerts-list">
            {alerts.length === 0 && (
              <li className="desk-alert-item desk-alert-item--ok">
                <span className="desk-alert-item__icon" aria-hidden>✓</span>
                <span className="desk-alert-item__body">
                  <span className="desk-alert-item__title">All systems operational</span>
                  <span className="desk-alert-item__meta">No alerts right now</span>
                </span>
              </li>
            )}
            {alerts.map(a => (
              <li key={a.id} className={`desk-alert-item desk-alert-item--${a.type}`}>
                <span className="desk-alert-item__icon" aria-hidden>
                  {a.type === 'error' ? '⚠' : a.type === 'warn' ? '!' : 'ℹ'}
                </span>
                <span className="desk-alert-item__body">
                  <span className="desk-alert-item__title">{a.title}</span>
                  <span className="desk-alert-item__meta">
                    {a.meta} · {a.ago}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
