import React, { useEffect, useMemo, useRef, useState } from 'react'
import { AccountCard, AccountMiniCard } from './AccountCard.jsx'
import { SegmentedControl } from './ui/SegmentedControl.jsx'
import {
  accountLabel,
  getAccountSlots,
  getLoggedInSlots,
  getNextAvailableSlot,
  isAccountLoggedIn,
  isSubscriptionAccount,
  isCampaignEnabled,
  isForwardingEnabled,
  isSlotOnShutdownList,
  filterSlotsExcludingShutdown,
  sortAccountsForDisplay,
} from '../utils/accountUi'
import { ShutdownListPanel } from './ShutdownListPanel.jsx'
import { SABHI, SABHI_SETUP } from '../utils/sabAccountsUi.js'
import { Spinner } from '../Loader.jsx'

const MODE_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'campaign', label: 'Campaign' },
  { value: 'forwarding', label: 'Forwarding' },
]
const MODE_FILTER_HINT = 'Filters the list. On Setup, use the Forward / Campaign tabs at the top.'

export function AccountPanel({
  state,
  configuredSlots,
  subscriptionSlots = [],
  accountsModeFilter = 'forwarding',
  hideAccountsModeFilter = false,
  workspaceMode = null,
  onAccountsModeFilterChange,
  onAccountChange,
  onStartAccount,
  onStopAccount,
  onSwitchAccount,
  onRefreshJoined,
  refreshingJoinedSlot,
  accountActionLoading,
  switchingAccount,
  onMessageSaved,
  onPostingModeUpdated,
  onShutdownUpdated,
  onRenamed,
  compactSetup = false,
  showShutdown = true,
  overviewScope = 'fleet',
  onShowFleetOverview,
  onOpenFleetTab,
  onProvisionSlot,
}) {
  const [provisioningSlot, setProvisioningSlot] = useState(false)
  const accountInfo = state.account_info || {}
  const accountStates = state.account_states || {}
  const postingModes = state.posting_modes || {}
  const accountShutdown = state.account_shutdown || {}
  const shutdownList = state.shutdown_list || {}
  const allSlots = getAccountSlots(state, configuredSlots)
  const subs = Array.isArray(subscriptionSlots) ? subscriptionSlots : []
  const modeFilter = accountsModeFilter
  const setModeFilter = onAccountsModeFilterChange || (() => {})

  const loggedInSlots = useMemo(
    () => sortAccountsForDisplay(
      getLoggedInSlots(allSlots, accountInfo),
      accountStates,
      accountInfo,
    ),
    [allSlots, accountInfo, accountStates],
  )

  const restingCount = useMemo(
    () => loggedInSlots.filter(slot =>
      isSlotOnShutdownList(accountShutdown, shutdownList, slot),
    ).length,
    [loggedInSlots, accountShutdown, shutdownList],
  )

  const activeLoggedInSlots = useMemo(
    () => filterSlotsExcludingShutdown(loggedInSlots, accountShutdown, shutdownList),
    [loggedInSlots, accountShutdown, shutdownList],
  )

  const modeCounts = useMemo(() => {
    let campaign = 0
    let forwarding = 0
    for (const slot of activeLoggedInSlots) {
      if (isCampaignEnabled(accountStates, slot, postingModes)) campaign += 1
      if (isForwardingEnabled(accountStates, slot, postingModes)) forwarding += 1
    }
    return { campaign, forwarding }
  }, [activeLoggedInSlots, accountStates, postingModes])

  const filteredSlots = useMemo(() => {
    // Always show ALL logged-in accounts, don't filter by mode
    // Users should see their accounts even if mode isn't configured yet
    return activeLoggedInSlots
  }, [activeLoggedInSlots])

  const nextAvailable = useMemo(
    () => getNextAvailableSlot(allSlots, accountInfo),
    [allSlots, accountInfo],
  )

  const visibleActive = useMemo(() => {
    const active = state.active_account
    const pickFirstActive = () => activeLoggedInSlots[0] ?? nextAvailable ?? null
    if (active && isAccountLoggedIn(accountInfo, active)) {
      if (!isSlotOnShutdownList(accountShutdown, shutdownList, active)) {
        return active
      }
      return pickFirstActive()
    }
    if (active && allSlots.includes(active) && !isAccountLoggedIn(accountInfo, active)) {
      return active
    }
    return pickFirstActive()
  }, [
    state.active_account,
    accountInfo,
    allSlots,
    activeLoggedInSlots,
    nextAvailable,
    accountShutdown,
    shutdownList,
  ])

  /** When the workspace picker is hidden, still filter the grid by Forward vs Campaign. */
  const showAllLoggedInGrid = hideAccountsModeFilter && modeFilter === 'all'

  const gridSlots = useMemo(() => {
    if (showAllLoggedInGrid) {
      if (
        visibleActive
        && isAccountLoggedIn(accountInfo, visibleActive)
        && !isSlotOnShutdownList(accountShutdown, shutdownList, visibleActive)
        && !activeLoggedInSlots.includes(visibleActive)
      ) {
        return sortAccountsForDisplay(
          [...activeLoggedInSlots, visibleActive],
          accountStates,
          accountInfo,
        )
      }
      return activeLoggedInSlots
    }
    return filteredSlots
  }, [
    showAllLoggedInGrid,
    activeLoggedInSlots,
    filteredSlots,
    visibleActive,
    accountInfo,
    accountStates,
    accountShutdown,
    shutdownList,
  ])

  const loginPanelRef = useRef(null)

  useEffect(() => {
    if (switchingAccount) return
    if (showAllLoggedInGrid) return
    if (!visibleActive) return
    // Empty slot (Add account) — keep selection so phone + OTP login stay visible.
    if (!isAccountLoggedIn(accountInfo, visibleActive)) return
    if (filteredSlots.includes(visibleActive)) return
    const next = filteredSlots[0]
    if (next && next !== visibleActive) {
      onSwitchAccount(next)
    }
  }, [
    showAllLoggedInGrid,
    modeFilter,
    filteredSlots,
    visibleActive,
    onSwitchAccount,
    accountShutdown,
    shutdownList,
    accountInfo,
    switchingAccount,
  ])

  function scrollToLoginPanel() {
    window.requestAnimationFrame(() => {
      loginPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }

  function selectAddAccountSlot() {
    if (!nextAvailable) return
    if (!hideAccountsModeFilter && modeFilter !== 'all') setModeFilter('all')
    onSwitchAccount(nextAvailable)
    scrollToLoginPanel()
  }

  async function handleAddAccount() {
    if (nextAvailable) {
      selectAddAccountSlot()
      return
    }
    if (!onProvisionSlot) return
    setProvisioningSlot(true)
    try {
      const slot = await onProvisionSlot()
      if (slot) scrollToLoginPanel()
    } catch (e) {
      alert(String(e.message || e))
    } finally {
      setProvisioningSlot(false)
    }
  }

  const addingAccount = !!(
    nextAvailable
    && visibleActive === nextAvailable
    && !isAccountLoggedIn(accountInfo, nextAvailable)
  )

  const showActiveCard = !!(
    visibleActive
    && !isSlotOnShutdownList(accountShutdown, shutdownList, visibleActive)
    && (
      modeFilter === 'all'
      || filteredSlots.includes(visibleActive)
      || addingAccount
    )
  )

  const sectionSub = loggedInSlots.length === 0
    ? 'No accounts logged in'
    : (() => {
        const activeN = activeLoggedInSlots.length
        const restBit = restingCount > 0
          ? ` · ${restingCount} resting (Shutdown tab)`
          : ''
        if (modeFilter === 'all' || showAllLoggedInGrid) {
          return `${activeN} accounts${restBit} · ${modeCounts.campaign} campaign · ${modeCounts.forwarding} forwarding`
        }
        const modeWord = modeFilter === 'forwarding' ? 'forwarding' : 'campaign'
        if (filteredSlots.length === 0) {
          return `No ${modeWord} accounts${restBit} — switch mode on a card or use ${modeFilter === 'forwarding' ? 'Forward' : 'Campaign'} setup`
        }
        return `${filteredSlots.length} ${modeWord}${restBit}`
      })()

  const showAddSlot = !!nextAvailable || typeof onProvisionSlot === 'function'
  const addBusy = switchingAccount != null || provisioningSlot
  const addLabel = nextAvailable ? 'Add account' : 'Add new slot'
  const addTitle = nextAvailable
    ? `Log in to ${accountLabel(nextAvailable)} (phone + OTP)`
    : 'Create another account slot (account11, account12, …) then log in'
  const showShutdownPanel = showShutdown && !compactSetup

  return (
    <section className={`accounts-section${compactSetup ? ' accounts-section--compact' : ''}`}>
      <header className="section-header section-header--compact accounts-section-head">
        <div className="accounts-section-head-text">
          <h2 className="section-title">Accounts</h2>
          <span className="section-sub">{sectionSub}</span>
        </div>
        {showAddSlot && !compactSetup && (
          <button
            type="button"
            className="btn btn--ghost btn--sm accounts-add-head-btn"
            onClick={handleAddAccount}
            disabled={addBusy}
            title={addTitle}
          >
            {provisioningSlot ? 'Adding…' : `+ ${addLabel}`}
          </button>
        )}
      </header>

      {showShutdownPanel && (
        <ShutdownListPanel
          shutdownList={shutdownList}
          accountShutdown={accountShutdown}
          accountInfo={accountInfo}
          onUpdated={onShutdownUpdated || onAccountChange}
        />
      )}

      {showAllLoggedInGrid && activeLoggedInSlots.length > 0 && modeCounts.campaign > 0 && (
        <p className="stat-hint accounts-grid-all-hint">
          All logged-in accounts are listed. Cards marked <strong>Campaign</strong> are not on
          Forwarding yet — use <strong>All → Forwarding + link</strong> on the <strong>{SABHI_SETUP}</strong> tab, or switch mode on the card.
        </p>
      )}

      {switchingAccount && (
        <p className="accounts-switching-status" role="status" aria-live="polite">
          <Spinner size={14} />
          <span>Switching to {accountLabel(switchingAccount)}…</span>
        </p>
      )}

      {loggedInSlots.length > 0 && !hideAccountsModeFilter && (
        <>
          <SegmentedControl
            className="accounts-mode-filter"
            label="Show accounts"
            options={MODE_FILTERS}
            value={modeFilter}
            onChange={setModeFilter}
            role="tablist"
          />
          <p className="accounts-mode-filter-hint">{MODE_FILTER_HINT}</p>
        </>
      )}

      <div className="accounts-grid" role="tablist" aria-label="Account selector">
        {compactSetup && (onOpenFleetTab || onShowFleetOverview) && (
          <button
            type="button"
            className={`account-mini account-mini--all${overviewScope === 'fleet' ? ' account-mini--selected' : ''}`}
            onClick={() => {
              if (typeof onOpenFleetTab === 'function') onOpenFleetTab()
              else onShowFleetOverview?.()
            }}
            aria-label={`${SABHI_SETUP} — same link or message for all accounts`}
            title={`Open ${SABHI_SETUP} tab`}
          >
            <span className="account-mini-top">
              <span className="account-mini-top-row">
                <span className="account-mini-slot">ALL</span>
                <span className="account-mini-status-pill account-mini-status-pill--fleet">{SABHI}</span>
              </span>
            </span>
            <span className="account-mini-name">{SABHI_SETUP}</span>
            <span className="account-mini-user">Shared link for every account</span>
          </button>
        )}
        {gridSlots.length === 0 && loggedInSlots.length > 0 ? (
          <p className="stat-hint accounts-grid-empty">
            {activeLoggedInSlots.length === 0 && restingCount > 0
              ? `All ${restingCount} logged-in account${restingCount !== 1 ? 's are' : ' is'} on shutdown rest — open the Shutdown tab to clear or wait for auto-resume.`
              : `No accounts on ${modeFilter === 'forwarding' ? 'forwarding' : 'campaign'} in this workspace${restingCount > 0 ? ` (${restingCount} resting on Shutdown tab)` : ''}. Open ${modeFilter === 'forwarding' ? 'Forward' : 'Campaign'} setup for an account, or switch workspace.`}
          </p>
        ) : (
          gridSlots.map(slot => (
            <AccountMiniCard
              key={slot}
              slot={slot}
              selected={visibleActive === slot}
              info={accountInfo[slot]}
              acctState={accountStates[slot]}
              accountStatus={state.account_status?.[slot]}
              accountShutdown={accountShutdown}
              postingModes={postingModes}
              accountStates={accountStates}
              switchingAccount={switchingAccount}
              isSubscription={isSubscriptionAccount(slot, subs, accountInfo)}
              onSelect={onSwitchAccount}
              onRenamed={onRenamed}
            />
          ))
        )}
        {showAddSlot && (
          <button
            type="button"
            className={`account-mini account-mini--add${
              (nextAvailable && visibleActive === nextAvailable) ? ' account-mini--selected' : ''
            }`}
            onClick={handleAddAccount}
            disabled={addBusy}
            aria-label={nextAvailable
              ? `Add account — log in to ${accountLabel(nextAvailable)}`
              : 'Add new account slot'}
            title={addTitle}
          >
            <span className="account-mini-add-icon">+</span>
            <span className="account-mini-add-label">
              {provisioningSlot ? 'Adding…' : addLabel}
            </span>
            {nextAvailable && (
              <span className="account-mini-add-slot">{accountLabel(nextAvailable)}</span>
            )}
          </button>
        )}
      </div>

      {!showActiveCard && modeFilter !== 'all' && filteredSlots.length === 0 && loggedInSlots.length > 0 && (
        <p className="stat-hint accounts-workspace-empty">
          No accounts on <strong>{modeFilter === 'forwarding' ? 'forwarding' : 'campaign'}</strong> yet.
          Open <strong>Forward or Campaign</strong> to switch an account.
        </p>
      )}

      {showActiveCard && (
        <>
        <div
          ref={
            !isAccountLoggedIn(accountInfo, visibleActive) ? loginPanelRef : undefined
          }
        >
        <AccountCard
          key={visibleActive}
          slot={visibleActive}
          label={accountLabel(visibleActive)}
          info={accountInfo[visibleActive]}
          isActive
          isSubscription={isSubscriptionAccount(visibleActive, subs, accountInfo)}
          acctRunning={
            !!(
              accountStates[visibleActive]?.running
              || accountStates[visibleActive]?.campaign_running
              || accountStates[visibleActive]?.forwarding_running
              || accountStates[visibleActive]?.campaign?.running
              || accountStates[visibleActive]?.forwarding?.running
            )
          }
          onLogin={onAccountChange}
          onLogout={onAccountChange}
          onStart={onStartAccount}
          onStop={onStopAccount}
          onRefreshJoined={onRefreshJoined}
          refreshingJoined={refreshingJoinedSlot === visibleActive}
          accountActionLoading={accountActionLoading}
          acctState={accountStates[visibleActive]}
          accountStatus={state.account_status?.[visibleActive]}
          accountShutdown={accountShutdown}
          forwardJob={state.forward_message_jobs?.[visibleActive]}
          statsWindow={state.daily_stats?.window}
          sentInWindow={state.daily_stats?.per_account?.[visibleActive]?.forwarded}
          customMessage={state.account_messages?.[visibleActive] ?? state.custom_message ?? ''}
          onMessageSaved={onMessageSaved}
          postingModeConfig={
            accountStates[visibleActive]?.posting_mode_config
            || postingModes[visibleActive]
          }
          onPostingModeUpdated={onPostingModeUpdated}
          postingModes={postingModes}
          accountStates={accountStates}
          setupFilter={modeFilter === 'all' ? 'all' : modeFilter}
          workspaceMode={workspaceMode}
          compactSetup={compactSetup}
          onRenamed={onRenamed}
        />
        </div>
        </>
      )}
    </section>
  )
}
