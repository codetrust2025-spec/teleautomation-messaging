import React, { useEffect, useMemo, useState } from 'react'
import { SetupMainPanel } from '../components/SetupMainPanel.jsx'
import { AccountPanel } from '../components/AccountPanel.jsx'
import { FleetDefaultsPanel } from '../components/FleetDefaultsPanel.jsx'
import { ShutdownListPanel } from '../components/ShutdownListPanel.jsx'
import { SetupAccountPicker } from '../components/SetupAccountPicker.jsx'
import { GroupsUpload } from '../components/GroupsUpload.jsx'
import { API } from '../config.js'
import {
  isForwardingEnabled,
  isCampaignEnabled,
  isSlotOnShutdownList,
} from '../utils/accountUi.js'
import { WORKSPACE_CAMPAIGN } from '../utils/workspaceMode.js'

function Drawer({ open, title, onClose, children }) {
  if (!open) return null
  return (
    <div className="fwd-drawer-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="fwd-drawer"
        role="dialog"
        aria-label={title}
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="fwd-drawer__head">
          <h2 className="fwd-drawer__title">{title}</h2>
          <button type="button" className="fwd-drawer__close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="fwd-drawer__body">{children}</div>
      </aside>
    </div>
  )
}

function CardHead({ num, title, desc, right }) {
  return (
    <header className="fwd-card__head">
      <span className="fwd-card__badge">{num}</span>
      <div className="fwd-card__titles">
        <h2 className="fwd-card__title">{title}</h2>
        <p className="fwd-card__desc">{desc}</p>
      </div>
      {right ? <div className="fwd-card__head-right">{right}</div> : null}
    </header>
  )
}

export function ForwarderConsole({
  state,
  workspaceMode,
  loggedInSlots = [],
  setupLoggedInSlots = [],
  postingModes = {},
  subscriptionSlots = [],
  switchingAccount,
  switchAccount,
  refreshAccounts,
  handleSetupAccountFilter,
  handleAccountModeApplied,
  modesProps,
  setupPanelProps,
  groupsUploadProps,
  shutdownListCount = 0,
  totalListLoading,
  onTotalList,
  onSetSetupTab,
}) {
  const [drawer, setDrawer] = useState(null) // 'setup' | 'accounts' | 'shutdown'
  const [defaults, setDefaults] = useState({ forward_source_url: '', campaign_message: '' })

  const accountStates = state.account_states || {}
  const accountShutdown = state.account_shutdown || {}
  const shutdownList = state.shutdown_list || {}
  const isCampaign = workspaceMode === WORKSPACE_CAMPAIGN

  useEffect(() => {
    let active = true
    fetch(`${API}/fleet/defaults`, { credentials: 'include' })
      .then((r) => r.json())
      .then((d) => { if (active && d) setDefaults({ forward_source_url: d.forward_source_url || '', campaign_message: d.campaign_message || '' }) })
      .catch(() => {})
    return () => { active = false }
  }, [state.fleet_defaults_rev])

  const activeSlots = useMemo(
    () => loggedInSlots.filter((s) => !isSlotOnShutdownList(accountShutdown, shutdownList, s)),
    [loggedInSlots, accountShutdown, shutdownList],
  )
  const forwardingCount = useMemo(
    () => activeSlots.filter((s) => isForwardingEnabled(accountStates, s, postingModes)).length,
    [activeSlots, accountStates, postingModes],
  )
  const campaignCount = useMemo(
    () => activeSlots.filter((s) => isCampaignEnabled(accountStates, s, postingModes)).length,
    [activeSlots, accountStates, postingModes],
  )
  const loggedInCount = loggedInSlots.length

  const modeLabel = isCampaign ? 'Campaign + message' : 'All → Forwarding + link'
  const defaultSummary = isCampaign
    ? (defaults.campaign_message || 'No campaign message set')
    : (defaults.forward_source_url || 'No default link set')

  return (
    <div className="fwd-console">
      {/*
        DOM order: right-col first (Login→Shutdown) then left-col (Setup→Bulk).
        CSS `order` restores desktop layout: left-col shows on left, right-col on right.
        Mobile collapses to single column, preserving DOM order:
          Login → Shutdown → Setup → Bulk  (wrong mobile order)
        To get Setup → Login → Bulk → Shutdown on mobile, we use CSS order values.
      */}

      {/* Left column (desktop): Setup → Bulk  |  mobile order: 1, 3 */}
      <div className="fwd-col fwd-col--left">
        <section className="fwd-card fwd-card--setup">
          <CardHead num="1" title="Setup" desc="Configure how forwarding works for your accounts." />
          <div className="fwd-card__body">
            <div className="fwd-config">
              <div className="fwd-config__label">Current configuration</div>
              <div className="fwd-config__row">
                <span className="fwd-config__k">Mode</span>
                <span className="fwd-config__v">{modeLabel}</span>
              </div>
              <div className="fwd-config__row">
                <span className="fwd-config__k">{isCampaign ? 'Campaign message' : 'Default post link'}</span>
                <span className="fwd-config__v fwd-config__v--link" title={defaultSummary}>{defaultSummary}</span>
              </div>
              <div className="fwd-config__row">
                <span className="fwd-config__k">Applied to</span>
                <span className="fwd-config__v">All logged-in accounts</span>
              </div>
            </div>
            <div className="fwd-statbox-row">
              <div className="fwd-statbox">
                <div className="fwd-statbox__n">{forwardingCount}</div>
                <div className="fwd-statbox__l">Forwarding accounts</div>
              </div>
              <div className="fwd-statbox">
                <div className="fwd-statbox__n">{campaignCount}</div>
                <div className="fwd-statbox__l">Campaigns</div>
              </div>
            </div>
          </div>
          <footer className="fwd-card__foot">
            <button type="button" className="fwd-btn fwd-btn--ghost" onClick={() => setDrawer('setup')}>
              ⚙ Edit configuration
            </button>
            <button type="button" className="fwd-link" disabled={!!totalListLoading} onClick={() => onTotalList?.()}>
              {totalListLoading ? 'Building…' : 'View forward list →'}
            </button>
          </footer>
        </section>

        <section className="fwd-card fwd-card--bulk">
          <CardHead num="3" title="Bulk" desc="Set default message/link for bulk forwarding." />
          <div className="fwd-card__body">
            <FleetDefaultsPanel
              embedInTab
              workspaceMode={workspaceMode}
              loggedInCount={setupLoggedInSlots.length}
              onUpdated={refreshAccounts}
            />
          </div>
        </section>
      </div>

      {/* Right column (desktop): Login → Shutdown  |  mobile order: 2, 4 */}
      <div className="fwd-col fwd-col--right">
        <section className="fwd-card fwd-card--login">
          <CardHead
            num="2"
            title="Log in"
            desc="Manage your account logins."
            right={(
              <div className="fwd-stat4">
                <span className="fwd-stat4__item"><b>{loggedInCount}</b>Logged in</span>
                <span className="fwd-stat4__item"><b>{shutdownListCount}</b>Shutdown rest</span>
                <span className="fwd-stat4__item"><b>{forwardingCount}</b>Forwarding</span>
                <span className="fwd-stat4__item"><b>{campaignCount}</b>Campaign</span>
              </div>
            )}
          />
          <div className="fwd-card__body">
            <div className="fwd-login-row">
              <button type="button" className="fwd-add-tile" onClick={() => setDrawer('accounts')}>
                <span className="fwd-add-tile__plus">+</span>
                <span className="fwd-add-tile__label">Add account</span>
              </button>
              <div className="fwd-login-summary">
                <div className="fwd-login-summary__label">Logged-in accounts</div>
                <div className="fwd-login-summary__big">{loggedInCount} account{loggedInCount !== 1 ? 's' : ''} ready</div>
              </div>
            </div>
          </div>
          <footer className="fwd-card__foot">
            <span className="fwd-muted">{loggedInCount > 0 ? `${loggedInCount} account${loggedInCount !== 1 ? 's' : ''} ready to use` : 'Not logged in'}</span>
            <div className="fwd-foot-actions">
              <button type="button" className="fwd-link" onClick={() => setDrawer('accounts')}>View all →</button>
              <button type="button" className="fwd-btn fwd-btn--green" onClick={() => setDrawer('accounts')}>+ Login</button>
            </div>
          </footer>
        </section>

        <section className="fwd-card fwd-card--shutdown">
          <CardHead
            num="4"
            title="Shutdown"
            desc="Manage accounts resting on shutdown."
            right={(
              <div className="fwd-shutdown-head-right">
                {shutdownListCount > 0 && <span className="fwd-pill fwd-pill--rest">{shutdownListCount} resting</span>}
                <button type="button" className="fwd-link" onClick={() => setDrawer('shutdown')}>View all →</button>
              </div>
            )}
          />
          <div className="fwd-card__body fwd-card__body--shutdown">
            <ShutdownListPanel
              shutdownList={shutdownList}
              accountShutdown={accountShutdown}
              accountInfo={state.account_info}
              onUpdated={refreshAccounts}
              embedInTab
              previewLimit={3}
            />
          </div>
        </section>
      </div>

      {/* ── Drawers ── */}
      <Drawer open={drawer === 'setup'} title="Setup configuration" onClose={() => setDrawer(null)}>
        <SetupMainPanel
          slots={setupLoggedInSlots}
          accountFilter={workspaceMode}
          onAccountFilterChange={handleSetupAccountFilter}
          onModeApplied={handleAccountModeApplied}
          activeSlot={state.active_account}
          accountInfo={state.account_info}
          accountStates={state.account_states}
          postingModes={postingModes}
          accountShutdown={state.account_shutdown}
          subscriptionSlots={subscriptionSlots}
          switchingAccount={switchingAccount}
          onSelectAccount={switchAccount}
          onOpenLoginTab={() => setDrawer('accounts')}
          onPostingModeUpdated={refreshAccounts}
          modesProps={modesProps}
        />
        {isCampaign && (
          <div className="fwd-drawer__section">
            <SetupAccountPicker
              slots={setupLoggedInSlots}
              activeSlot={state.active_account}
              accountInfo={state.account_info}
              accountStates={state.account_states}
              postingModes={postingModes}
              accountShutdown={state.account_shutdown}
              subscriptionSlots={subscriptionSlots}
              switchingAccount={switchingAccount}
              onSelect={switchAccount}
              onOpenAccountsTab={() => setDrawer('accounts')}
            />
            <GroupsUpload {...groupsUploadProps} />
          </div>
        )}
      </Drawer>

      <Drawer open={drawer === 'accounts'} title="Accounts" onClose={() => setDrawer(null)}>
        <AccountPanel {...setupPanelProps.accountPanel} />
      </Drawer>

      <Drawer open={drawer === 'shutdown'} title="Shutdown list" onClose={() => setDrawer(null)}>
        <ShutdownListPanel
          shutdownList={shutdownList}
          accountShutdown={accountShutdown}
          accountInfo={state.account_info}
          onUpdated={refreshAccounts}
          embedInTab
        />
      </Drawer>
    </div>
  )
}
