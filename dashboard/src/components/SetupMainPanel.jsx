import React, { useEffect, useMemo } from 'react'
import { SetupAccountPicker } from './SetupAccountPicker.jsx'
import { SetupAccountFilter } from './SetupAccountFilter.jsx'
import { AccountModeSwitcher } from './AccountModeSwitcher.jsx'
import { ModesSetupPanel } from './ModesSetupPanel.jsx'
import {
  accountPrimaryMode,
  isCampaignEnabled,
  isForwardingEnabled,
} from '../utils/accountUi.js'
import { WORKSPACE_CAMPAIGN, WORKSPACE_FORWARDING } from '../utils/workspaceMode.js'

/**
 * Setup: filter tabs → pick account → change method → start → link/message.
 */
export function SetupMainPanel({
  slots = [],
  activeSlot,
  accountFilter = WORKSPACE_FORWARDING,
  onAccountFilterChange,
  onModeApplied,
  accountInfo,
  accountStates,
  postingModes,
  accountShutdown,
  subscriptionSlots,
  switchingAccount,
  onSelectAccount,
  onOpenLoginTab,
  onPostingModeUpdated,
  modesProps,
}) {
  const counts = useMemo(() => {
    let forwarding = 0
    let campaign = 0
    for (const slot of slots) {
      if (isForwardingEnabled(accountStates, slot, postingModes)) forwarding += 1
      if (isCampaignEnabled(accountStates, slot, postingModes)) campaign += 1
    }
    return { forwarding, campaign }
  }, [slots, accountStates, postingModes])

  const filteredSlots = useMemo(() => {
    if (accountFilter === WORKSPACE_CAMPAIGN) {
      return slots.filter(slot => isCampaignEnabled(accountStates, slot, postingModes))
    }
    return slots.filter(slot => isForwardingEnabled(accountStates, slot, postingModes))
  }, [slots, accountFilter, accountStates, postingModes])

  useEffect(() => {
    if (!filteredSlots.length || !onSelectAccount) return
    if (activeSlot && filteredSlots.includes(activeSlot)) return
    onSelectAccount(filteredSlots[0])
  }, [accountFilter, filteredSlots.join(','), activeSlot, onSelectAccount])

  const loggedIn = activeSlot && accountInfo?.[activeSlot]
  const accountMode = activeSlot
    ? accountPrimaryMode(accountStates, activeSlot, postingModes)
    : 'off'
  const filterLabel = accountFilter === WORKSPACE_CAMPAIGN ? 'Campaign' : 'Forward'
  const filterWants = accountFilter === WORKSPACE_CAMPAIGN ? 'campaign' : 'forwarding'
  const onOtherTab = loggedIn && accountMode !== 'off' && accountMode !== filterWants
  const canRunHere = loggedIn && accountMode === filterWants

  const runWorkspace =
    accountMode === 'campaign'
      ? WORKSPACE_CAMPAIGN
      : accountMode === 'forwarding'
        ? WORKSPACE_FORWARDING
        : accountFilter

  return (
    <div className="setup-main">
      <SetupAccountFilter
        value={accountFilter}
        onChange={onAccountFilterChange}
        forwardCount={counts.forwarding}
        campaignCount={counts.campaign}
      />

      <section className="setup-main__block" aria-labelledby="setup-main-account">
        <h3 id="setup-main-account" className="setup-main__heading">
          <span className="setup-main__num">1</span> Account
          <span className="setup-main__heading-sub">{filterLabel} list</span>
        </h3>

        {filteredSlots.length === 0 ? (
          <div className="setup-main__block--muted setup-main__empty-filter">
            <p className="stat-hint">
              No <strong>{filterLabel}</strong> accounts on this tab. Use step 2 after picking any account on the
              other tab, or <strong>Bulk</strong>.
            </p>
          </div>
        ) : (
          <SetupAccountPicker
            slots={filteredSlots}
            activeSlot={activeSlot}
            accountInfo={accountInfo}
            accountStates={accountStates}
            postingModes={postingModes}
            accountShutdown={accountShutdown}
            subscriptionSlots={subscriptionSlots}
            switchingAccount={switchingAccount}
            onSelect={onSelectAccount}
            onOpenAccountsTab={onOpenLoginTab}
          />
        )}
      </section>

      {!loggedIn ? (
        <section className="setup-main__block setup-main__block--muted">
          <p className="stat-hint setup-main__pick-hint">
            Select an account above, or open <strong>Log in</strong>.
          </p>
        </section>
      ) : (
        <>
          <section
            className="setup-main__block setup-main__block--type"
            aria-labelledby="setup-main-change-type"
          >
            <h3 id="setup-main-change-type" className="setup-main__heading">
              <span className="setup-main__num">2</span> Change method
            </h3>
            <AccountModeSwitcher
              slot={activeSlot}
              postingModeConfig={modesProps?.postingModeConfig}
              postingModes={postingModes}
              accountStates={accountStates}
              onUpdated={onPostingModeUpdated}
              onModeApplied={onModeApplied}
            />
          </section>

          {onOtherTab && (
            <p className="setup-main__tab-note" role="status">
              Account is on <strong>{accountMode}</strong> — switch to <strong>{filterWants}</strong> in step 2, or
              open the <strong>{accountMode}</strong> tab to start it here.
            </p>
          )}

          {canRunHere ? (
            <ModesSetupPanel {...modesProps} workspaceMode={runWorkspace} slot={activeSlot} />
          ) : (
            <section className="setup-main__block setup-main__block--muted">
              <p className="stat-hint">
                Step 3 (Start) appears when this account matches the <strong>{filterLabel}</strong> tab.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  )
}
