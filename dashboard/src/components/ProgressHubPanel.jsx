import React, { useMemo, useState } from 'react'
import { ButtonContent } from '../Loader.jsx'
import { DailyStatsPanel } from './DailyStatsPanel.jsx'
import { ProgressStatsPanel, ProgressStatChip } from './ProgressStatsPanel.jsx'
import { AccountFleetGrid } from './AccountFleetGrid.jsx'
import { FleetHealthPanel } from './FleetHealthPanel.jsx'
import { AccountPerformanceChart } from './AccountPerformanceChart.jsx'
import { ProgressSection } from './ProgressSection.jsx'
import { ProgressBar } from './ui/ProgressBar.jsx'
import {
  accountLabel,
  formatCountdown,
  getAccountStatus,
  setupViewForAccountsFilter,
} from '../utils/accountUi'
import { buildFleetHealthRows, sortFleetHealthRows } from '../utils/fleetHealth.js'
import { computeSuccessRatePct } from '../utils/globalStats.js'
import {
  SABHI,
  SABHI_ACCOUNTS,
  SABHI_ACCOUNTS_COMBINED,
  SABHI_CYCLE,
  SABHI_HEALTH,
  SABHI_OVERVIEW,
  SABHI_PROGRESS,
  SABHI_TODAY_REACH,
} from '../utils/sabAccountsUi.js'
import { SegmentedControl } from './ui/SegmentedControl.jsx'

const SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'fleet', label: SABHI },
  { id: 'performance', label: 'Performance' },
  { id: 'accounts', label: 'Accounts' },
  { id: 'selected', label: 'Selected' },
]

function ProgressHubPin({
  fleet,
  globalCountdown,
  alertCount,
  activeAccountLabel,
  accountPin,
}) {
  const pinFleet = accountPin || fleet
  const {
    runningCount,
    sleepingCount,
    sending,
    hasAnyCycle,
    progressValue,
    progressMax,
  } = pinFleet

  let statusLabel = 'Idle'
  if (sending.length > 0) {
    statusLabel = sending.length === 1 ? 'Sending' : `${sending.length} sending`
  } else if (runningCount > 0) {
    statusLabel = globalCountdown > 0 ? 'Waiting' : 'Running'
  } else if (sleepingCount > 0) {
    statusLabel = 'Sleeping'
  }

  const activeCount = runningCount + sleepingCount

  return (
    <div className="progress-hub-pin" role="status" aria-live="polite">
      <span className={`progress-hub-pin-status progress-hub-pin-status--${statusLabel.toLowerCase().replace(/\s+/g, '_')}`}>
        {statusLabel}
      </span>
      {globalCountdown > 0 && activeCount > 0 && (
        <span className="progress-hub-pin-countdown">{formatCountdown(globalCountdown)}</span>
      )}
      <span className="progress-hub-pin-stat" title="Accounts running or paused">
        <strong>{activeCount}</strong> active
      </span>
      <span className="progress-hub-pin-stat" title={`${SABHI_CYCLE} progress`}>
        <strong>{hasAnyCycle ? progressValue : 0}/{progressMax}</strong> groups
      </span>
      {alertCount > 0 && (
        <span className="progress-hub-pin-alert" title="Accounts needing attention">
          {alertCount} alert{alertCount !== 1 ? 's' : ''}
        </span>
      )}
      {activeAccountLabel && (
        <span className="progress-hub-pin-account" title={accountPin ? 'Account overview' : SABHI_OVERVIEW}>
          {activeAccountLabel}
        </span>
      )}
    </div>
  )
}

export function ProgressHubPanel({
  overviewScope = 'fleet',
  accountsModeFilter = 'all',
  onShowFleetOverview,
  fleet,
  globalCountdown,
  sentWindowLabel,
  accountInfo,
  subscriptionSlots,
  dailyStats,
  accountSlots,
  onDailyStatsUpdate,
  onConfirmReset,
  activeAccount,
  activeAcctState,
  accountStatus,
  accountShutdown,
  accountStates,
  postingModes = {},
  onSelectAccount,
  switchingAccount,
  accountProgress,
  cycle,
  tools,
}) {
  const [section, setSection] = useState('overview')
  const [layout, setLayout] = useState('single')

  const subs = subscriptionSlots?.length ? subscriptionSlots : []
  const showAccountOverview = overviewScope === 'account' && !!activeAccount
  const activeAccountLabel = showAccountOverview && activeAccount
    ? accountLabel(activeAccount)
    : null

  const alertCount = useMemo(() => {
    const resetTs = dailyStats?.reset_timestamp ?? 0
    const rows = sortFleetHealthRows(
      buildFleetHealthRows(
        fleet.perAccount,
        accountInfo,
        dailyStats?.window,
        resetTs,
      ),
    )
    return rows.filter(r => r.attention).length
  }, [fleet.perAccount, accountInfo, dailyStats?.window, dailyStats?.reset_timestamp])

  const fleetChipsSecondary = (
    <>
      <ProgressStatChip
        label={accountsModeFilter === 'forwarding' ? 'Remaining this tick' : 'Still to post'}
        value={fleet.needResend}
        title={accountsModeFilter === 'forwarding'
          ? 'Groups left in the current forward batch'
          : `Groups still waiting across ${SABHI_ACCOUNTS.toLowerCase()}`}
      />
      <ProgressStatChip label="Skipped (already posted)" value={fleet.skippedAlreadyPosted} warn title={`Skipped — ${SABHI_ACCOUNTS.toLowerCase()}`} />
      {fleet.skippedCooldown + fleet.skippedOther > 0 && (
        <ProgressStatChip
          label="Paused to avoid spam"
          value={fleet.skippedCooldown + fleet.skippedOther}
          warn
          icon="⏳"
          helper="Temporary safety delay"
          title="Groups temporarily paused due to safe messaging delay. They are delayed, not failed."
        />
      )}
      <ProgressStatChip
        label={accountsModeFilter === 'forwarding'
          ? `Forward posts (${sentWindowLabel.toLowerCase()})`
          : `Sent (${sentWindowLabel.toLowerCase()})`}
        value={fleet.messagesSent24h}
        title={accountsModeFilter === 'forwarding'
          ? `Successful forwards since reset — cumulative, not this tick`
          : `Forwards — ${sentWindowLabel.toLowerCase()} — ${SABHI_ACCOUNTS.toLowerCase()}`}
      />
    </>
  )

  const {
    displaySuccess,
    displayFailed,
    displayActiveGroups,
    displayTickTotal,
    displayTickRemaining,
    displaySkippedPosted,
    displaySkippedCooldown,
    displaySkippedOther,
    displaySent24h,
  } = accountProgress

  const accountProgressView = setupViewForAccountsFilter(
    accountsModeFilter,
    activeAccount,
    accountStates,
    postingModes,
  )
  const isForwardAccountProgress = accountProgressView === 'forwarding' && showAccountOverview

  const accountSliceSize = activeAcctState?.my_groups?.length ?? 0
  const accountProcessed = isForwardAccountProgress
    ? (displaySuccess + displayFailed + displaySkippedPosted)
    : (displaySuccess + displayFailed)
  const accountSuccessRate = computeSuccessRatePct(displaySuccess, displayFailed)
  const accountProgressMax = isForwardAccountProgress
    ? (displayTickTotal || displayActiveGroups || activeAcctState?.forward_batch_size || 100)
    : (accountSliceSize || 1)
  const accountSkipped = Math.max(0, accountSliceSize - (displayActiveGroups || 0))
  const accountProgressValue = isForwardAccountProgress
    ? (activeAcctState?.running || cycle.hasCycleRun ? accountProcessed : 0)
    : (cycle.hasCycleRun
      ? Math.min(accountProgressMax, accountSkipped + accountProcessed)
      : 0)

  const accountChipsSecondary = isForwardAccountProgress ? (
    <>
      <ProgressStatChip
        label="Remaining this tick"
        value={displayTickRemaining ?? Math.max(0, (displayTickTotal || displayActiveGroups || 0) - accountProcessed)}
        title="Groups not yet attempted in the current forward batch"
      />
      <ProgressStatChip
        label="Skipped (already posted)"
        value={displaySkippedPosted}
        warn
        title="Skipped this forward tick — already posted"
      />
      <ProgressStatChip label="Failed" value={displayFailed} warn title="Failed forwards this tick" />
      <ProgressStatChip
        label={`Forward posts (${sentWindowLabel.toLowerCase()})`}
        value={displaySent24h}
        title={`Successful forwards since reset — cumulative, not this tick`}
      />
    </>
  ) : (
    <>
      <ProgressStatChip label="Still to post" value={displayActiveGroups} title="Groups still waiting this cycle — this account" />
      <ProgressStatChip label="Skipped (already posted)" value={displaySkippedPosted} warn title="Skipped — this account" />
      {displaySkippedCooldown + displaySkippedOther > 0 && (
        <ProgressStatChip
          label="Paused to avoid spam"
          value={displaySkippedCooldown + displaySkippedOther}
          warn
          icon="⏳"
          helper="Temporary safety delay"
          title="Groups temporarily paused due to safe messaging delay. They are delayed, not failed."
        />
      )}
      <ProgressStatChip
        label={`Sent (${sentWindowLabel.toLowerCase()})`}
        value={displaySent24h}
        title={`Posts — ${sentWindowLabel.toLowerCase()} — this account`}
      />
    </>
  )

  const accountPin = useMemo(() => {
    if (!showAccountOverview || !activeAcctState) return null
    const loggedIn = !!accountInfo?.[activeAccount]
    const status = getAccountStatus(
      activeAcctState,
      loggedIn,
      accountStatus?.[activeAccount],
      accountShutdown,
      activeAccount,
    )
    const sending = activeAcctState?.running && activeAcctState?.current_group
      ? [{ slot: activeAccount, group: activeAcctState.current_group }]
      : []
    return {
      runningCount: status === 'running' ? 1 : 0,
      sleepingCount: status === 'sleeping' ? 1 : 0,
      sending,
      hasAnyCycle: cycle.hasCycleRun,
      progressValue: accountProgressValue,
      progressMax: accountProgressMax,
    }
  }, [
    showAccountOverview,
    activeAcctState,
    activeAccount,
    accountInfo,
    accountStatus,
    accountShutdown,
    cycle.hasCycleRun,
    accountProgressValue,
    accountProgressMax,
  ])

  function renderOverviewScopeBar() {
    if (!showAccountOverview) return null
    return (
      <div className="progress-hub-scope-bar">
        <span className="progress-hub-scope-label">
          Showing <strong>{activeAccountLabel}</strong>
        </span>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={onShowFleetOverview}
        >
          ← {SABHI_ACCOUNTS}
        </button>
      </div>
    )
  }

  function renderOverview() {
    if (showAccountOverview) {
      return (
        <div className="progress-hub-section">
          {renderOverviewScopeBar()}
          <DailyStatsPanel
            dailyStats={dailyStats}
            accountSlots={accountSlots}
            accountInfo={accountInfo}
            accountStates={accountStates}
            onConfirmReset={onConfirmReset}
            onDailyStatsUpdate={onDailyStatsUpdate}
            scopeAccount={activeAccount}
            accountsModeFilter={accountsModeFilter}
            postingModes={postingModes}
          />
          <ProgressStatsPanel
            title={isForwardAccountProgress
              ? (activeAccountLabel ? `${activeAccountLabel} · forward tick` : 'Forward tick summary')
              : (activeAccountLabel || 'Account cycle summary')}
            subtitle={isForwardAccountProgress
              ? `This tick only. Cumulative “Forward posts (since reset)” is in ${SABHI_TODAY_REACH}.`
              : `This account only — combined totals are under ${SABHI_ACCOUNTS}`}
            helpText={isForwardAccountProgress
              ? 'Sent / skipped / failed are for the active forward batch only. Success rate is sent ÷ (sent + failed); skipped groups are not counted as attempts.'
              : `Select another account in the sidebar or use ← ${SABHI_ACCOUNTS} for combined metrics.`}
            totalGroups={isForwardAccountProgress
              ? (displayTickTotal || displayActiveGroups || 0)
              : accountSliceSize}
            success={displaySuccess}
            failed={displayFailed}
            successRate={accountSuccessRate}
            processed={accountProcessed}
            secondary={accountChipsSecondary}
            successLabel={isForwardAccountProgress ? 'Sent this tick' : 'Posted OK'}
            processedHint={isForwardAccountProgress ? 'groups this tick' : 'tried this cycle'}
            groupsLabel={isForwardAccountProgress ? 'Groups this tick' : 'Groups in list'}
            successTitle={isForwardAccountProgress
              ? 'Successful forwards in the current batch only'
              : 'Messages posted successfully this cycle'}
            rateTitle={isForwardAccountProgress
              ? 'Sent ÷ (sent + failed) for this tick — skips excluded'
              : 'Share of send attempts that succeeded (posted OK ÷ sent + failed)'}
          >
            <ProgressBar
              value={cycle.hasCycleRun ? accountProgressValue : 0}
              max={accountProgressMax}
              label={isForwardAccountProgress
                ? `Forward tick: ${accountProgressValue} of ${accountProgressMax} groups`
                : `Account progress: ${cycle.hasCycleRun ? accountProgressValue : 0} of ${accountProgressMax} groups processed this cycle`}
              tone="success"
              large
              className="fleet-progress-bar"
            />
          </ProgressStatsPanel>
        </div>
      )
    }

    return (
      <div className="progress-hub-section">
        <DailyStatsPanel
          dailyStats={dailyStats}
          accountSlots={accountSlots}
          accountInfo={accountInfo}
          accountStates={accountStates}
          onConfirmReset={onConfirmReset}
          onDailyStatsUpdate={onDailyStatsUpdate}
          accountsModeFilter={accountsModeFilter}
        />
        <ProgressStatsPanel
          title={accountsModeFilter === 'forwarding' ? 'Forward tick summary' : `${SABHI_CYCLE} summary`}
          subtitle={accountsModeFilter === 'forwarding'
            ? `This tick only — forwarding accounts. Cumulative totals are in ${SABHI_TODAY_REACH} above.`
            : `Primary metrics — ${SABHI_ACCOUNTS_COMBINED}`}
          helpText={accountsModeFilter === 'forwarding'
            ? 'Posted OK / Failed / Success rate reflect the current forward batch only (rate = sent ÷ sent+failed). “Forward posts (since reset)” in the reach panel is the running total.'
            : 'Select an account in the sidebar to see its overview, or use other tabs for health and ranking.'}
          totalGroups={accountsModeFilter === 'forwarding' ? fleet.progressMax : (fleet.masterTotal || 0)}
          success={fleet.success}
          failed={fleet.failed}
          successRate={fleet.successRate}
          processed={fleet.processed}
          secondary={fleetChipsSecondary}
          successLabel={accountsModeFilter === 'forwarding' ? 'Sent this tick' : 'Posted OK'}
          failedLabel="Failed"
          successRateLabel="Success rate"
          processedHint={accountsModeFilter === 'forwarding' ? 'groups this tick' : 'tried this cycle'}
          groupsLabel={accountsModeFilter === 'forwarding' ? 'Groups this tick' : 'Groups in list'}
          successTitle={accountsModeFilter === 'forwarding'
            ? 'Successful forwards in the current batch only'
            : 'Messages posted successfully this cycle'}
          failedTitle={accountsModeFilter === 'forwarding'
            ? 'Failed forwards in the current batch only'
            : 'Groups where posting failed this cycle'}
          rateTitle={accountsModeFilter === 'forwarding'
            ? 'Sent ÷ (sent + failed) for this tick — skips excluded'
            : 'Share of send attempts that succeeded (posted OK ÷ sent + failed)'}
        >
          <ProgressBar
            value={fleet.hasAnyCycle ? fleet.progressValue : 0}
            max={fleet.progressMax}
            label={accountsModeFilter === 'forwarding'
              ? `Forward tick: ${fleet.hasAnyCycle ? fleet.progressValue : 0} of ${fleet.progressMax} groups`
              : `${SABHI_PROGRESS}: ${fleet.hasAnyCycle ? fleet.progressValue : 0} of ${fleet.progressMax} groups processed this cycle`}
            tone="success"
            large
            className="fleet-progress-bar"
          />
        </ProgressStatsPanel>
      </div>
    )
  }

  function renderFleet() {
    return (
      <div className="progress-hub-section progress-hub-section--scroll">
        {fleet.perAccount.length > 0 ? (
          <FleetHealthPanel
            perAccount={fleet.perAccount}
            accountInfo={accountInfo}
            statsWindow={dailyStats?.window}
            dailyStats={dailyStats}
          />
        ) : (
          <p className="stat-hint">No logged-in accounts to show {SABHI_HEALTH.toLowerCase()}.</p>
        )}
      </div>
    )
  }

  function renderPerformance() {
    return (
      <div className="progress-hub-section progress-hub-section--scroll">
        {fleet.perAccount.length > 0 ? (
          <AccountPerformanceChart
            perAccount={fleet.perAccount}
            accountInfo={accountInfo}
            statsWindow={dailyStats?.window}
            subscriptionSlots={subs}
            rankingOnly
          />
        ) : (
          <p className="stat-hint">No performance data yet.</p>
        )}
      </div>
    )
  }

  function renderAccounts() {
    return (
      <div className="progress-hub-section progress-hub-section--scroll">
        <AccountFleetGrid
          perAccount={fleet.perAccount}
          accountInfo={accountInfo}
          accountStates={accountStates}
          subscriptionSlots={subs}
          activeAccount={activeAccount}
          onSelectAccount={onSelectAccount}
          switchingAccount={switchingAccount}
          onAccountSelected={() => setSection('selected')}
        />
      </div>
    )
  }

  function renderSelected() {
    return (
      <div className="progress-hub-section progress-hub-section--scroll">
        <ProgressStatsPanel
          title={activeAccountLabel ? activeAccountLabel : 'Selected account'}
          subtitle="Cycle deep dive — combined status is in the top bar"
          hideGrid
          secondary={(
            <>
              <ProgressStatChip
                label={isForwardAccountProgress ? 'Sent this tick' : 'Posted OK'}
                value={displaySuccess}
                title={isForwardAccountProgress
                  ? 'Successful forwards this tick — this account only'
                  : 'Sent this cycle — this account only'}
              />
              <ProgressStatChip label="Failed" value={displayFailed} title="Failed this cycle — this account only" />
              <ProgressStatChip
                label={isForwardAccountProgress ? 'Remaining this tick' : 'Still to post'}
                value={isForwardAccountProgress
                  ? (displayTickRemaining ?? Math.max(0, (displayTickTotal || displayActiveGroups || 0) - (displaySuccess + displayFailed + displaySkippedPosted)))
                  : displayActiveGroups}
                title={isForwardAccountProgress
                  ? 'Groups not yet attempted in the current forward batch'
                  : 'Groups waiting this cycle'}
              />
              <ProgressStatChip label="Already in chat" value={displaySkippedPosted} warn title="Skipped — already posted" />
              {displaySkippedCooldown + displaySkippedOther > 0 && (
                <ProgressStatChip
                  label="Paused to avoid spam"
                  value={displaySkippedCooldown + displaySkippedOther}
                  warn
                  icon="⏳"
                  helper="Temporary safety delay"
                  title="Groups temporarily paused due to safe messaging delay. They are delayed, not failed."
                />
              )}
              <ProgressStatChip
                label={`Sent (${sentWindowLabel.toLowerCase()})`}
                value={displaySent24h}
                title={`Forwards — ${sentWindowLabel.toLowerCase()} — this account`}
              />
            </>
          )}
        >
          <ProgressSection
            activeAcctState={activeAcctState}
            displayCurrentGroup={cycle.displayCurrentGroup}
            countdown={cycle.countdown}
            cycleElapsed={cycle.cycleElapsed}
            progressValue={cycle.progressValue}
            progressMax={cycle.progressMax}
            hasCycleRun={cycle.hasCycleRun}
            deepDive
          />
        </ProgressStatsPanel>

        <div className="controls-row controls-panel controls-panel--account">
          <div className="action-group">
            <button type="button" className="btn btn--accent btn--sm" onClick={tools.openGroups} disabled={tools.loadingGroups}>
              <ButtonContent loading={tools.loadingGroups} loadingLabel="Loading…">
                View groups
              </ButtonContent>
            </button>
            <button
              type="button"
              className="btn btn--danger btn--sm"
              onClick={() => tools.exportGroupLists('dead')}
              disabled={!!tools.exportingKind}
            >
              <ButtonContent loading={tools.exportingKind === 'dead'} loadingLabel="…">Dead list</ButtonContent>
            </button>
            <button
              type="button"
              className="btn btn--success btn--sm"
              onClick={() => tools.exportGroupLists('good')}
              disabled={!!tools.exportingKind}
            >
              <ButtonContent loading={tools.exportingKind === 'good'} loadingLabel="…">Active list</ButtonContent>
            </button>
            <button type="button" className="btn btn--ghost btn--sm" onClick={tools.onResetStats}>
              Reset stats
            </button>
          </div>
        </div>
      </div>
    )
  }

  const sectionRenderers = {
    overview: renderOverview,
    fleet: renderFleet,
    performance: renderPerformance,
    accounts: renderAccounts,
    selected: renderSelected,
  }

  return (
    <div className="progress-hub">
      <ProgressHubPin
        fleet={fleet}
        globalCountdown={globalCountdown}
        alertCount={alertCount}
        activeAccountLabel={showAccountOverview ? activeAccountLabel : SABHI_ACCOUNTS}
        accountPin={accountPin}
      />

      <div className="progress-hub-nav">
        <SegmentedControl
          className="progress-hub-tabs"
          label="Progress sections"
          role="tablist"
          options={SECTIONS.map(s => ({
            value: s.id,
            label: s.label,
            role: 'tab',
            controls: `progress-hub-panel-${s.id}`,
          }))}
          value={section}
          onChange={(next) => {
            setLayout('single')
            setSection(next)
          }}
        />
        <SegmentedControl
          className="progress-hub-layout-toggle"
          label="Layout mode"
          options={[
            { value: 'single', label: 'Single' },
            { value: 'split', label: 'Split' },
          ]}
          value={layout}
          onChange={setLayout}
        />
      </div>

      <div className={`progress-hub-body progress-hub-body--${layout}`}>
        {layout === 'single' ? (
          <div
            id={`progress-hub-panel-${section}`}
            className="progress-hub-pane"
            role="tabpanel"
            aria-label={`${SECTIONS.find(s => s.id === section)?.label || 'Overview'} panel`}
          >
            {(sectionRenderers[section] || renderOverview)()}
          </div>
        ) : (
          <>
            <div className="progress-hub-pane progress-hub-pane--split" aria-label={SABHI_HEALTH}>
              <h4 className="progress-hub-split-title">{SABHI_HEALTH}</h4>
              {renderFleet()}
            </div>
            <div className="progress-hub-pane progress-hub-pane--split" aria-label="Top performers">
              <h4 className="progress-hub-split-title">Top performers</h4>
              {renderPerformance()}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
