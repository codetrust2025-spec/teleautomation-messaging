import React, { useMemo, useState } from 'react'
import { formatCountdown } from '../utils/accountUi.js'
import { applyAccountPostingMode } from '../utils/accountPostingMode.js'
import {
  WORKSPACE_CAMPAIGN,
  WORKSPACE_FORWARDING,
  WORKSPACE_MODE_OPTIONS,
} from '../utils/workspaceMode.js'
import { getDashboardModeConfig } from '../utils/workspaceDashboard.js'
import { SegmentedControl } from '../components/ui/SegmentedControl.jsx'
import { SABHI, SABHI_ACCOUNTS } from '../utils/sabAccountsUi.js'
import { MobHealthRing } from './MobHealthRing.jsx'
import { MobSparkline } from './MobSparkline.jsx'
import { accountRowsForMobile, computeMobileStats } from './mobileUtils.js'

export function MobileDashboardHome({
  state,
  loggedInSlots,
  postingModes,
  workspaceMode,
  onWorkspaceModeChange,
  anyProcessRunning = false,
  inboxUnreadTotal,
  fleet,
  globalCountdown,
  sentWindowLabel,
  activeSlot,
  overviewScope = 'fleet',
  onSelectAccount,
  onSelectAllAccounts,
  onRefreshAccounts,
  onStartAccount,
  onStopAccount,
  accountActionLoading,
  shutdownListCount = 0,
  onOpenSetup,
  onOpenProgress,
  onResetReach,
  onNavBulk,
  onNavShutdown,
  onNavLogs,
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [modeLoading, setModeLoading] = useState(false)

  const mode = getDashboardModeConfig(workspaceMode)

  const stats = useMemo(
    () =>
      computeMobileStats({
        state,
        loggedInSlots,
        postingModes,
        inboxUnreadTotal,
        fleet,
        modeFilter: mode.modeFilter,
      }),
    [state, loggedInSlots, postingModes, inboxUnreadTotal, fleet, mode.modeFilter, workspaceMode],
  )

  const accounts = useMemo(
    () => accountRowsForMobile(state, loggedInSlots, postingModes, mode.modeFilter),
    [state, loggedInSlots, postingModes, mode.modeFilter],
  )

  const active = accounts.find(a => a.slot === activeSlot) || accounts[0]
  const showAll = overviewScope === 'fleet'
  const barDisplay = showAll
    ? {
        initials: SABHI,
        color: '#5b21b6',
        displayName: SABHI_ACCOUNTS,
        subLabel: `${accounts.length} accounts`,
      }
    : active
  const activeRunning = active?.running
  const progressPct = stats.progressMax > 0
    ? Math.round((stats.progressValue / stats.progressMax) * 100)
    : 0

  const methodValue =
    workspaceMode === WORKSPACE_CAMPAIGN ? 'campaign' : 'forwarding'

  const accountTotal = mode.isFleet ? stats.totalAccounts : stats.modeEnabledCount
  const accountRunning = stats.displayRunning ?? stats.runningAccounts
  const accountResting = stats.displayResting ?? stats.restingAccounts
  const runningNow = mode.isCampaign ? stats.campRunning : stats.fwdRunning
  const postsSent = stats.postsToday ?? stats.messagesSent24h ?? 0
  const fleetBusy =
    anyProcessRunning
    || accounts.some(row => row.running)
    || stats.sleeping
    || (Number(fleet?.runningCount) || 0) > 0
    || (Number(fleet?.sleepingCount) || 0) > 0
  const quickBusy = fleetBusy

  async function setMethod(nextMode) {
    if (!activeSlot || modeLoading) return
    const want = nextMode === 'campaign' ? WORKSPACE_CAMPAIGN : WORKSPACE_FORWARDING
    onWorkspaceModeChange?.(want)
    setModeLoading(true)
    const result = await applyAccountPostingMode(activeSlot, nextMode)
    setModeLoading(false)
    if (!result.ok) {
      alert(result.error)
    } else {
      onRefreshAccounts?.()
    }
  }

  function quickStart() {
    if (!activeSlot) return
    onStartAccount?.(activeSlot, false, mode.feature)
  }

  function quickStop() {
    if (!activeSlot) return
    onStopAccount?.(activeSlot, mode.feature)
  }

  const workspaceOptions = WORKSPACE_MODE_OPTIONS.map(opt => ({
    value: opt.value,
    label: opt.value === WORKSPACE_FORWARDING ? '↻ Forwarding' : '📣 Campaign',
    role: 'tab',
  }))

  return (
    <div className={`mob-dash mob-dash--sigma${mode.isCampaign ? ' mob-dash--campaign' : ''}${mode.isForwarding ? ' mob-dash--forwarding' : ''}`}>
      <div className="mob-workspace-tabs">
        <SegmentedControl
          className="mob-workspace-tabs__control"
          label="Workspace"
          options={workspaceOptions}
          value={workspaceMode}
          onChange={onWorkspaceModeChange}
          role="tablist"
        />
      </div>
      {accounts.length > 0 && barDisplay && (
        <div className="mob-account-bar">
          <button
            type="button"
            className="mob-account-bar__pick"
            onClick={() => setPickerOpen(true)}
          >
            <span
              className="mob-account-bar__avatar"
              style={{ background: barDisplay.color }}
              aria-hidden
            >
              {barDisplay.initials}
            </span>
            <span className="mob-account-bar__text">
              <span className="mob-account-bar__sub">{barDisplay.subLabel}</span>
              <span className="mob-account-bar__name">
                {barDisplay.displayName}
                <span className="mob-account-bar__chev" aria-hidden>▾</span>
              </span>
            </span>
          </button>
          <button
            type="button"
            className="mob-account-bar__stop"
            disabled={!activeSlot || !activeRunning || !!accountActionLoading}
            onClick={quickStop}
          >
            <span className="mob-account-bar__stop-icon" aria-hidden>■</span>
            Stop
          </button>
        </div>
      )}

      <div className="mob-stats-scroll" role="list">
        <div className="mob-stat-card mob-stat-card--green" role="listitem">
          <div className="mob-stat-card__top">
            <span className="mob-stat-card__icon" aria-hidden>👥</span>
            <span className="mob-stat-card__label">Accounts</span>
          </div>
          <div className="mob-stat-card__value">{accountTotal}</div>
          <div className="mob-stat-card__sub">
            {accountRunning} running · {accountResting} resting
          </div>
          <MobSparkline color="#22c55e" variant="line" />
        </div>
        <div className="mob-stat-card mob-stat-card--blue" role="listitem">
          <div className="mob-stat-card__top">
            <span className="mob-stat-card__icon" aria-hidden>{mode.isCampaign ? '📣' : '✈'}</span>
            <span className="mob-stat-card__label">{mode.postsKpiLabel}</span>
          </div>
          <div className="mob-stat-card__value mob-stat-card__value--blue">{postsSent}</div>
          <div className="mob-stat-card__sub">{sentWindowLabel?.toLowerCase() || 'since reset'}</div>
          <MobSparkline color={mode.isCampaign ? '#f97316' : '#3b82f6'} variant="line" />
        </div>
        <div className="mob-stat-card mob-stat-card--purple" role="listitem">
          <div className="mob-stat-card__top">
            <span className="mob-stat-card__icon" aria-hidden>✉</span>
            <span className="mob-stat-card__label">Inbox</span>
          </div>
          <div className="mob-stat-card__value mob-stat-card__value--purple">
            {stats.inboxNew}
          </div>
          <div className="mob-stat-card__sub">New messages</div>
          <MobSparkline color="#8b5cf6" variant="bars" />
        </div>
        <div className="mob-stat-card mob-stat-card--orange" role="listitem">
          <div className="mob-stat-card__top">
            <span className="mob-stat-card__icon" aria-hidden>📣</span>
            <span className="mob-stat-card__label">
              {mode.isCampaign ? 'Active campaigns' : 'Campaigns'}
            </span>
          </div>
          <div className="mob-stat-card__value mob-stat-card__value--orange">
            {stats.campRunning}
          </div>
          <div className="mob-stat-card__sub">
            {mode.isCampaign ? 'posting' : 'running'}
          </div>
          <MobSparkline color="#f97316" variant="flat" />
        </div>
      </div>

      <div className="mob-card mob-system-card">
        <div className="mob-section-head">
          <h2 className="mob-section-title" style={{ margin: 0 }}>{mode.performanceTitle}</h2>
          <button type="button" className="mob-section-head__link" onClick={onOpenProgress}>
            View all
          </button>
        </div>
        <div className="mob-system-body">
          <MobHealthRing
            percent={stats.healthPercent}
            label={stats.healthPercent >= 80 ? 'Healthy' : 'Attention'}
          />
          <div className="mob-system-meta">
            <div className="mob-system-dots">
              <span className="mob-system-dot mob-system-dot--ok">
                <span className="mob-system-dot__n">{stats.activeTasks}</span> Active tasks
              </span>
              <span className="mob-system-dot mob-system-dot--fail">
                <span className="mob-system-dot__n">{stats.failedCount}</span> Failed
              </span>
              <span className="mob-system-dot mob-system-dot--warn">
                <span className="mob-system-dot__n">{stats.alertCount}</span> Alerts
              </span>
            </div>
            {stats.sleeping && (
              <p className="mob-system-sleep">
                ⏱ Sleeping {formatCountdown(globalCountdown || stats.countdown)}
              </p>
            )}
            <div className="mob-progress-bar" aria-hidden>
              <div
                className="mob-progress-bar__fill"
                style={{ width: `${Math.min(100, progressPct)}%` }}
              />
            </div>
            <div className="mob-progress-foot">
              <span>{mode.tickFootLabel}</span>
              <strong>
                {stats.progressValue} / {stats.progressMax} groups
              </strong>
            </div>
          </div>
        </div>
      </div>

      <div className="mob-card">
        <h2 className="mob-section-title">Quick actions</h2>
        <div className="mob-quick-grid">
          {!quickBusy ? (
            <button
              type="button"
              className="mob-quick-tile mob-quick-tile--start"
              disabled={!activeSlot || !!accountActionLoading}
              onClick={quickStart}
            >
              <span className="mob-quick-tile__icon" aria-hidden>▶</span>
              <span className="mob-quick-tile__label">{mode.startLabel}</span>
            </button>
          ) : (
            <button
              type="button"
              className="mob-quick-tile mob-quick-tile--stop"
              disabled={!activeSlot || !!accountActionLoading}
              onClick={quickStop}
            >
              <span className="mob-quick-tile__icon" aria-hidden>■</span>
              <span className="mob-quick-tile__label">{mode.stopLabel}</span>
            </button>
          )}
          <button type="button" className="mob-quick-tile mob-quick-tile--dark" onClick={onNavBulk}>
            <span className="mob-quick-tile__icon mob-quick-tile__icon--blue" aria-hidden>☰</span>
            <span className="mob-quick-tile__label">{mode.bulkLabel}</span>
          </button>
          <button
            type="button"
            className="mob-quick-tile mob-quick-tile--dark"
            onClick={onNavShutdown}
          >
            <span className="mob-quick-tile__icon mob-quick-tile__icon--red" aria-hidden>⏻</span>
            <span className="mob-quick-tile__label">
              Shutdown{shutdownListCount > 0 ? ` (${shutdownListCount})` : ''}
            </span>
          </button>
          <button type="button" className="mob-quick-tile mob-quick-tile--dark" onClick={onNavLogs}>
            <span className="mob-quick-tile__icon mob-quick-tile__icon--purple" aria-hidden>📋</span>
            <span className="mob-quick-tile__label">Logs</span>
          </button>
          <button
            type="button"
            className="mob-quick-tile mob-quick-tile--dark"
            onClick={() => window.open('/submit-slot', '_blank', 'noopener,noreferrer')}
          >
            <span className="mob-quick-tile__icon mob-quick-tile__icon--green" aria-hidden>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
            </span>
            <span className="mob-quick-tile__label">Book slot</span>
          </button>
        </div>
      </div>

      <div className="mob-card">
        <div className="mob-section-head">
          <h2 className="mob-section-title" style={{ margin: 0 }}>
            {mode.reachTitle}
          </h2>
          <button type="button" className="mob-section-head__link" onClick={onResetReach}>
            Reset 24h
          </button>
        </div>
        <div className="mob-reach-grid mob-reach-grid--4">
          <div className="mob-reach-item">
            <div className="mob-reach-item__label">{mode.postsTodayLabel}</div>
            <div className="mob-reach-item__value mob-stat__value--green">{postsSent}</div>
            <div className="mob-reach-item__sub">{sentWindowLabel?.toLowerCase() || 'since reset'}</div>
          </div>
          <div className="mob-reach-item">
            <div className="mob-reach-item__label">{mode.runningNowLabel}</div>
            <div className="mob-reach-item__value mob-stat__value--blue">{runningNow}</div>
            <div className="mob-reach-item__sub">accounts</div>
          </div>
          <div className="mob-reach-item">
            <div className="mob-reach-item__label">Current sent</div>
            <div className="mob-reach-item__value mob-reach-item__value--amber">{stats.tickSent}</div>
            <div className="mob-reach-item__sub">this tick</div>
          </div>
          <div className="mob-reach-item">
            <div className="mob-reach-item__label">Success rate</div>
            <div className="mob-reach-item__value mob-stat__value--purple">
              {stats.successRate == null || stats.successRate === '—' ? '—' : `${stats.successRate}%`}
            </div>
            <div className="mob-reach-item__sub">{stats.fwdGroups} groups</div>
          </div>
        </div>
      </div>

      <div className="mob-card">
        <div className="mob-section-head">
          <h2 className="mob-section-title" style={{ margin: 0 }}>
            {mode.isCampaign ? 'Campaign accounts' : mode.isForwarding ? 'Forwarding accounts' : 'Accounts'}
          </h2>
          <button type="button" className="mob-section-head__link" onClick={onOpenSetup}>
            Manage ›
          </button>
        </div>
        {accounts.length === 0 && (
          <p className="mob-mode-hint">
            No accounts have {mode.isCampaign ? 'campaign' : 'forwarding'} enabled.
          </p>
        )}
        {accounts.slice(0, 6).map(row => (
          <button
            key={row.slot}
            type="button"
            className="mob-account-row"
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
        {accounts.length > 6 && (
          <button type="button" className="mob-accounts-more" onClick={onOpenSetup}>
            View all {accounts.length} accounts ›
          </button>
        )}
        <div className="mob-accounts-footer">
          <span>{accountTotal} in {mode.isCampaign ? 'campaign' : mode.isForwarding ? 'forwarding' : 'fleet'}</span>
          <span className="mob-accounts-footer__run">{accountRunning} Running</span>
          <span className="mob-accounts-footer__rest">{accountResting} Resting</span>
        </div>
      </div>

      {pickerOpen && (
        <>
          <div
            className="mob-picker-backdrop"
            role="presentation"
            onClick={() => setPickerOpen(false)}
          />
          <div className="mob-picker-sheet" role="dialog" aria-label="Choose account">
            <p className="mob-picker-sheet__title">Choose scope</p>
            <button
              type="button"
              className={`mob-account-row mob-account-row--all${showAll ? ' mob-account-row--selected' : ''}`}
              onClick={() => {
                onSelectAllAccounts?.()
                setPickerOpen(false)
              }}
            >
              <span
                className="mob-account-row__avatar"
                style={{ background: '#5b21b6' }}
                aria-hidden
              >
                {SABHI}
              </span>
              <span className="mob-account-row__info">
                <div className="mob-account-row__name">{SABHI_ACCOUNTS}</div>
                <div className="mob-account-row__sub">Combined stats for every account</div>
              </span>
              {showAll && (
                <span className="mob-status-pill mob-status-pill--running">Selected</span>
              )}
            </button>
            <p className="mob-picker-sheet__title" style={{ marginTop: 8 }}>Individual accounts</p>
            {accounts.map(row => {
              const selected = !showAll && row.slot === activeSlot
              return (
                <button
                  key={row.slot}
                  type="button"
                  className={`mob-account-row${selected ? ' mob-account-row--selected' : ''}`}
                  onClick={() => {
                    onSelectAccount?.(row.slot)
                    setPickerOpen(false)
                  }}
                >
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
                  {selected && (
                    <span className="mob-status-pill mob-status-pill--running">Selected</span>
                  )}
                </button>
              )
            })}
            <p className="mob-picker-sheet__title" style={{ marginTop: 12 }}>Change method</p>
            <div className="mob-method-toggle" role="group" aria-label="Change method">
              <button
                type="button"
                className={`mob-method-toggle__btn${methodValue === 'campaign' ? ' mob-method-toggle__btn--active' : ''}`}
                disabled={modeLoading || !activeSlot}
                onClick={() => setMethod('campaign')}
              >
                📣 Campaign
              </button>
              <button
                type="button"
                className={`mob-method-toggle__btn${methodValue === 'forwarding' ? ' mob-method-toggle__btn--active' : ''}`}
                disabled={modeLoading || !activeSlot}
                onClick={() => setMethod('forwarding')}
              >
                ↻ Forwarding
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
