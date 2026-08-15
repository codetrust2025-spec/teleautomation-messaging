import React, { useState, useRef, useEffect } from 'react'
import { accountRowsForDashboard, activeFleetSlots } from '../dashboard/dashboardStats.js'
import { getDashboardModeConfig } from '../utils/workspaceDashboard.js'
import { SABHI, SABHI_ACCOUNTS } from '../utils/sabAccountsUi.js'
import { MailNotificationBell } from '../components/MailMonitoringNotifications.jsx'

export function DesktopHeader({
  activeAccount,
  accountInfo,
  loggedInSlots,
  postingModes,
  state,
  workspaceMode,
  overviewScope = 'fleet',
  activeRunning,
  anyRunning,
  canStartMore,
  bulkActionLoading,
  onStartAll,
  onStopAll,
  totalListLoading,
  onTotalList,
  fleet,
  onSelectAccount,
  onSelectAllAccounts,
  inboxUnreadTotal,
  inboxUnreadBadge,
  onOpenInbox,
  authUsername,
  authEnabled,
  authLogout,
  connected,
  theme,
  onToggleTheme,
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const wrapRef = useRef(null)
  const userMenuRef = useRef(null)

  const mode = getDashboardModeConfig(workspaceMode)
  const fleetSlots = activeFleetSlots(
    {
      account_shutdown: state?.account_shutdown,
      shutdown_list: state?.shutdown_list,
    },
    loggedInSlots,
  )
  const accounts = accountRowsForDashboard(
    {
      account_info: accountInfo,
      account_states: state?.account_states,
      account_status: state?.account_status,
      account_shutdown: state?.account_shutdown,
      shutdown_list: state?.shutdown_list,
    },
    fleetSlots,
    postingModes,
    mode.modeFilter,
  )
  const active = accounts.find(a => a.slot === activeAccount) || accounts[0]
  const showAll = overviewScope === 'fleet'
  const headerDisplay = showAll
    ? {
        initials: SABHI,
        color: '#5b21b6',
        displayName: SABHI_ACCOUNTS,
      }
    : active

  useEffect(() => {
    if (!pickerOpen && !userMenuOpen) return undefined
    function onDoc(e) {
      if (pickerOpen && wrapRef.current && !wrapRef.current.contains(e.target)) {
        setPickerOpen(false)
      }
      if (userMenuOpen && userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [pickerOpen, userMenuOpen])

  const userInitials = (authUsername || 'AD').slice(0, 2).toUpperCase()
  const accountsRunning = accounts.some(row => row.running)
  const fleetTickBusy =
    (Number(fleet?.runningCount) || 0) > 0 || (Number(fleet?.sleepingCount) || 0) > 0
  const headerBusy = anyRunning || accountsRunning || fleetTickBusy
  const systemOk = connected && (headerBusy || true)

  return (
    <header className="desktop-header desktop-header--sigma">
      <div className="desktop-header__account-wrap" ref={wrapRef}>
        {accounts.length > 0 && headerDisplay && (
          <button
            type="button"
            className="desktop-header__account"
            onClick={() => setPickerOpen(v => !v)}
            aria-expanded={pickerOpen}
            aria-haspopup="listbox"
          >
            <span
              className="desktop-header__account-avatar"
              style={{ background: headerDisplay.color }}
              aria-hidden
            >
              {headerDisplay.initials}
            </span>
            <span className="desktop-header__account-text">
              <span className="desktop-header__account-name">
                {headerDisplay.displayName} <span aria-hidden>▾</span>
              </span>
            </span>
          </button>
        )}
        {pickerOpen && (
          <div className="desk-account-picker" role="listbox" aria-label="Account scope">
            <button
              type="button"
              role="option"
              aria-selected={showAll}
              className={`desk-account-row desk-account-row--all${showAll ? ' desk-account-row--selected' : ''}`}
              onClick={() => {
                onSelectAllAccounts?.()
                setPickerOpen(false)
              }}
            >
              <span
                className="mob-account-row__avatar desk-account-row__avatar--all"
                style={{ background: '#5b21b6' }}
                aria-hidden
              >
                {SABHI}
              </span>
              <span className="mob-account-row__info">
                <div className="mob-account-row__name">{SABHI_ACCOUNTS}</div>
                <div className="mob-account-row__sub">
                  {accounts.length} account{accounts.length !== 1 ? 's' : ''} · combined stats
                </div>
              </span>
              {showAll && <span className="desk-account-picker__check" aria-hidden>✓</span>}
            </button>
            <div className="desk-account-picker__divider" role="separator" />
            {accounts.map(row => {
              const selected = !showAll && row.slot === activeAccount
              return (
                <button
                  key={row.slot}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={`desk-account-row${selected ? ' desk-account-row--selected' : ''}`}
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
                  {selected && <span className="desk-account-picker__check" aria-hidden>✓</span>}
                </button>
              )
            })}
          </div>
        )}
      </div>

      <div className="desktop-header__status-center">
        <span
          className={`desktop-header__status-pulse${systemOk && connected ? '' : ' desktop-header__status-pulse--warn'}`}
          aria-hidden
        />
        <span className="desktop-header__status-text">
          {connected
            ? headerBusy
              ? 'System running smoothly — All systems operational'
              : mode.isCampaign
                ? 'Ready — Start campaign when you are'
                : 'Ready — Start forwarding when you are'
            : 'Reconnecting to server…'}
        </span>
      </div>

      <div className="desktop-header__actions">
        {headerBusy ? (
          <button
            type="button"
            className="desktop-header__bulk desktop-header__bulk--stop"
            disabled={!!bulkActionLoading}
            onClick={onStopAll}
          >
            ■ Stop all
          </button>
        ) : (
          <button
            type="button"
            className="desktop-header__bulk desktop-header__bulk--start"
            disabled={!canStartMore || !!bulkActionLoading}
            onClick={onStartAll}
          >
            ▶ Start all
          </button>
        )}

        {onTotalList && (
          <button
            type="button"
            className="desktop-header__icon-btn desktop-header__icon-btn--util"
            onClick={onTotalList}
            disabled={totalListLoading}
            title="Download joined groups CSV for all accounts"
            aria-label="Total list CSV"
          >
            <span aria-hidden>{totalListLoading ? '…' : '📋'}</span>
            <span className="desktop-header__util-label">List</span>
          </button>
        )}

        <button
          type="button"
          className="desktop-header__icon-btn"
          aria-label="Inbox notifications"
          onClick={onOpenInbox}
        >
          🔔
          {inboxUnreadTotal > 0 && (
            <span className="desktop-header__icon-badge">{inboxUnreadBadge}</span>
          )}
        </button>

        <MailNotificationBell />

        <button
          type="button"
          className="desktop-header__icon-btn desktop-header__theme-btn"
          aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
          aria-pressed={theme === 'light'}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
          onClick={onToggleTheme}
        >
          <span aria-hidden>{theme === 'light' ? '☾' : '☀'}</span>
        </button>

        <div className="desktop-header__user-wrap" ref={userMenuRef}>
          <button
            type="button"
            className="desktop-header__user"
            aria-label="User menu"
            aria-expanded={userMenuOpen}
            onClick={() => setUserMenuOpen(v => !v)}
          >
            {userInitials}
          </button>
          {userMenuOpen && (
            <div className="desk-user-menu" role="menu">
              <p className="desk-user-menu__label">Signed in as</p>
              <p className="desk-user-menu__name">{authUsername || 'Administrator'}</p>
              {authEnabled ? (
                <button
                  type="button"
                  className="desk-user-menu__item desk-user-menu__item--danger"
                  role="menuitem"
                  onClick={() => {
                    setUserMenuOpen(false)
                    authLogout?.()
                  }}
                >
                  Sign out
                </button>
              ) : (
                <p className="desk-user-menu__hint">Dashboard login is not required on this server.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
