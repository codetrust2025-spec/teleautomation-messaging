import React, { useEffect, useMemo, useState } from 'react'
import { API } from '../config.js'
import { ButtonContent } from '../Loader.jsx'
import {
  accountLabel,
  featureRuntime,
  isCampaignEnabled,
  isForwardingEnabled,
  postingModeForSlot,
} from '../utils/accountUi.js'
import { MetricBlock, MetricGrid } from './ui/MetricBlock.jsx'
import { FORWARDING_METRIC_HELP } from '../utils/fleetReachHelp.js'
import {
  SABHI_ACCOUNTS,
  SABHI_ACCOUNTS_COMBINED,
  SABHI_DAILY_LIMIT,
  SABHI_TODAY_REACH,
} from '../utils/sabAccountsUi.js'
import { formatIstDateTime } from '../utils/istTime.js'
import { SegmentedControl } from './ui/SegmentedControl.jsx'

const REACH_VIEWS = [
  { value: 'all', label: 'All' },
  { value: 'campaign', label: 'Campaign cycles' },
  { value: 'forwarding', label: 'Forwarding' },
]

function windowLabel(dailyStats, scopeAccount) {
  const who = scopeAccount ? accountLabel(scopeAccount) : SABHI_ACCOUNTS
  if (dailyStats?.window === 'since_reset' && dailyStats?.reset_at) {
    try {
      const d = new Date(dailyStats.reset_at)
      if (!Number.isNaN(d.getTime())) {
        return `${who} · since reset · ${formatIstDateTime(d.reset_at)} IST`
      }
    } catch { /* ignore */ }
    return `${who} · since last reset`
  }
  return `${who} · rolling last 24 hours`
}

function sumScopedStats(dailyStats, accountSlots, accountStates, scopeAccount, pick) {
  if (scopeAccount) {
    const row = dailyStats?.per_account?.[scopeAccount] || {}
    return pick(row)
  }
  let total = 0
  for (const slot of accountSlots) {
    const row = dailyStats?.per_account?.[slot] || {}
    total += pick(row)
  }
  return total
}

function sumByPostingMode(dailyStats, accountSlots, accountStates, postingModes, mode, pick) {
  let total = 0
  for (const slot of accountSlots) {
    if (mode === 'campaign' && !isCampaignEnabled(accountStates, slot, postingModes)) continue
    if (mode === 'forwarding' && !isForwardingEnabled(accountStates, slot, postingModes)) continue
    const row = dailyStats?.per_account?.[slot] || {}
    total += pick(row)
  }
  return total
}

function accountMatchesReachView(mode, reachView) {
  if (reachView === 'forwarding') return mode === 'forwarding'
  if (reachView === 'campaign') return mode === 'campaign'
  return true
}

function countAccountsInMode(accountSlots, accountStates, postingModes, mode) {
  if (mode === 'campaign') {
    return accountSlots.filter(s => isCampaignEnabled(accountStates, s, postingModes)).length
  }
  return accountSlots.filter(s => isForwardingEnabled(accountStates, s, postingModes)).length
}

/**
 * Today reach — two views: campaign cycles vs forwarding.
 */
export function DailyStatsPanel({
  dailyStats,
  accountSlots,
  accountInfo,
  accountStates,
  onDailyStatsUpdate,
  onConfirmReset,
  scopeAccount = null,
  accountsModeFilter = 'all',
  postingModes = {},
}) {
  const [resetting, setResetting] = useState(null)
  const [toast, setToast] = useState(null)
  const [reachView, setReachView] = useState('all')

  useEffect(() => {
    if (accountsModeFilter === 'forwarding' || accountsModeFilter === 'campaign') {
      setReachView(accountsModeFilter)
    } else if (accountsModeFilter === 'all') {
      setReachView('all')
    }
  }, [accountsModeFilter])

  useEffect(() => {
    if (!toast) return undefined
    const id = window.setTimeout(() => setToast(null), 3200)
    return () => clearTimeout(id)
  }, [toast])

  const scoped = scopeAccount ? (dailyStats?.per_account?.[scopeAccount] || {}) : null
  const g = dailyStats?.global || {}

  const contacts = scoped ? (scoped.contacts ?? 0) : (g.contacts ?? 0)
  const incoming = scoped ? (scoped.incoming ?? 0) : (g.incoming ?? 0)
  const outgoing = scoped ? (scoped.outgoing ?? 0) : (g.outgoing ?? 0)
  const campaignPosts = scoped
    ? (scoped.campaign_posts ?? scoped.forwarded ?? 0)
    : sumScopedStats(dailyStats, accountSlots, accountStates, null, r => r.campaign_posts ?? r.forwarded ?? 0)
  const forwardPosts = scoped
    ? (scoped.forward_posts ?? 0)
    : sumScopedStats(dailyStats, accountSlots, accountStates, null, r => r.forward_posts ?? 0)

  const campaignPostsInMode = scopeAccount
    ? (isCampaignEnabled(accountStates, scopeAccount, postingModes) ? campaignPosts : 0)
    : sumByPostingMode(dailyStats, accountSlots, accountStates, postingModes, 'campaign', r => r.campaign_posts ?? r.forwarded ?? 0)
  const forwardPostsInMode = scopeAccount
    ? (isForwardingEnabled(accountStates, scopeAccount, postingModes) ? forwardPosts : 0)
    : sumByPostingMode(dailyStats, accountSlots, accountStates, postingModes, 'forwarding', r => r.forward_posts ?? 0)

  const joinedToday = scopeAccount
    ? (Number(accountStates?.[scopeAccount]?.join_stats?.joins_today) || 0)
    : accountSlots.reduce((sum, slot) => {
        const joinStats = accountStates?.[slot]?.join_stats
        return sum + (Number(joinStats?.joins_today) || 0)
      }, 0)
  const joinLimit = scopeAccount
    ? (Number(accountStates?.[scopeAccount]?.join_stats?.joins_daily_limit) || 0)
    : accountSlots.reduce((sum, slot) => {
        const limit = accountStates?.[slot]?.join_stats?.joins_daily_limit
        return sum + (Number(limit) || 0)
      }, 0)

  const fleetCycle = useMemo(() => {
    let success = 0
    let failed = 0
    let skipped = 0
    for (const slot of accountSlots) {
      if (!isCampaignEnabled(accountStates, slot, postingModes)) continue
      const st = accountStates?.[slot] || {}
      const c = st.campaign || {}
      success += Number(c.success ?? st.campaign_success ?? 0)
      failed += Number(c.failed ?? st.campaign_failed ?? 0)
      skipped += Number(c.skipped_already_posted ?? st.campaign_skipped_already_posted ?? 0)
    }
    return { success, failed, skipped }
  }, [accountSlots, accountStates, postingModes])

  const fleetForward = useMemo(() => {
    let sent = 0
    let skipped = 0
    let failed = 0
    let running = 0
    for (const slot of accountSlots) {
      if (!isForwardingEnabled(accountStates, slot, postingModes)) continue
      const st = accountStates?.[slot] || {}
      const f = st.forwarding || {}
      if (st.forwarding_running || f.running) running += 1
      sent += Number(f.success ?? st.forwarding_success ?? 0)
      skipped += Number(f.skipped_already_posted ?? 0)
      failed += Number(f.failed ?? st.forwarding_failed ?? 0)
    }
    return { sent, skipped, failed, running }
  }, [accountSlots, accountStates, postingModes])

  const accountsCampaign = countAccountsInMode(accountSlots, accountStates, postingModes, 'campaign')
  const accountsForwarding = countAccountsInMode(accountSlots, accountStates, postingModes, 'forwarding')

  async function handleReset(scope = 'global', accountId = null) {
    const resetKey = scope === 'account' ? accountId : 'global'
    if (resetting) return

    const label = scope === 'account' ? accountLabel(accountId) : null
    const ok = await onConfirmReset({ scope, accountId, accountLabel: label })
    if (!ok) return

    setResetting(resetKey)
    try {
      const body = scope === 'account'
        ? { scope: 'account', account_id: accountId }
        : { scope: 'global' }
      const res = await fetch(`${API}/stats/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.status === 'error') {
        const msg = data.message || data.error || 'Could not reset stats'
        setToast(msg)
        return
      }
      if (data?.daily_stats && onDailyStatsUpdate) {
        onDailyStatsUpdate(data.daily_stats, data)
      }
      setToast(
        scope === 'account'
          ? `${label} stats reset successfully`
          : 'Stats reset successfully',
      )
    } finally {
      setResetting(null)
    }
  }

  const perAccount = dailyStats?.per_account || {}
  const ranked = [...accountSlots]
    .map(slot => ({
      slot,
      mode: postingModeForSlot(accountStates, slot),
      ...(perAccount[slot] || {}),
    }))
    .filter(row => {
      if (accountsModeFilter === 'forwarding') return row.mode === 'forwarding'
      if (accountsModeFilter === 'campaign') return row.mode === 'campaign'
      return accountMatchesReachView(row.mode, reachView)
    })
    .sort((a, b) => {
      const score = row => {
        const posts = (row.campaign_posts ?? row.forwarded ?? 0) + (row.forward_posts ?? 0)
        if (reachView === 'forwarding') return row.forward_posts ?? 0
        if (reachView === 'campaign') {
          return (row.campaign_posts ?? row.forwarded ?? 0)
            + (row.contacts || 0)
            + (row.incoming || 0)
            + (row.outgoing || 0)
        }
        return posts + (row.contacts || 0) + (row.incoming || 0) + (row.outgoing || 0)
      }
      return score(b) - score(a)
    })
    .filter(row => {
      if (reachView === 'forwarding') return (row.forward_posts ?? 0) > 0
      if (reachView === 'campaign') {
        return (row.campaign_posts ?? row.forwarded ?? 0) > 0
          || (row.contacts || 0) + (row.incoming || 0) + (row.outgoing || 0) > 0
      }
      return (row.campaign_posts ?? row.forwarded ?? 0) > 0
        || (row.forward_posts ?? 0) > 0
        || (row.contacts || 0) + (row.incoming || 0) + (row.outgoing || 0) > 0
    })

  const globalResetting = resetting === 'global'
  const accountResetting = scopeAccount && resetting === scopeAccount
  const statsTitle = scopeAccount
    ? 'Today reach'
    : accountsModeFilter === 'forwarding'
      ? `${SABHI_TODAY_REACH} · forwarding`
      : accountsModeFilter === 'campaign'
        ? `${SABHI_TODAY_REACH} · campaign`
        : SABHI_TODAY_REACH
  /* Setup filter only locks combined reach; per-account view keeps All / Campaign / Forwarding tabs */
  const lockReachView = !scopeAccount
    && (accountsModeFilter === 'forwarding' || accountsModeFilter === 'campaign')

  return (
    <section className="daily-stats-panel" aria-label={scopeAccount ? 'Account today reach' : `${SABHI_TODAY_REACH} and daily counters`}>
      <header className="daily-stats-header">
        <div>
          <h3 className="daily-stats-title">{statsTitle}</h3>
          <p className="daily-stats-sub">{windowLabel(dailyStats, scopeAccount)}</p>
        </div>
        <button
          type="button"
          className="btn btn--warn btn--sm daily-stats-reset-btn"
          onClick={() => (scopeAccount ? handleReset('account', scopeAccount) : handleReset('global'))}
          disabled={!!resetting}
          title={scopeAccount
            ? `Reset daily counters for ${accountLabel(scopeAccount)}`
            : 'Reset all daily counters to zero from now'}
        >
          <ButtonContent loading={scopeAccount ? accountResetting : globalResetting} loadingLabel="Resetting…">
            Reset 24 Hours
          </ButtonContent>
        </button>
      </header>

      {!lockReachView ? (
        <SegmentedControl
          className="daily-stats-view-tabs"
          label="Reach stats view"
          options={REACH_VIEWS}
          value={reachView}
          onChange={setReachView}
          role="tablist"
        />
      ) : (
        <p className="daily-stats-view-locked">
          Showing <strong>{accountsModeFilter === 'forwarding' ? 'Forwarding' : 'Campaign cycles'}</strong>
          {' '}— change the Accounts filter in Setup to switch views.
        </p>
      )}

      {reachView === 'all' ? (
        <>
          {!scopeAccount && (
            <p className="daily-stats-view-hint">
              {accountsCampaign} account{accountsCampaign === 1 ? '' : 's'} on campaign cycles
              {accountsForwarding > 0 ? ` · ${accountsForwarding} on forwarding` : ''}
            </p>
          )}
          <MetricGrid columns={4} className="daily-stats-grid">
            <MetricBlock label="Contacts" value={contacts} tone="success" title={`Unique DM contacts in this window (${SABHI_ACCOUNTS.toLowerCase()})`} />
            <MetricBlock label="Incoming" value={incoming} title="Incoming private messages" />
            <MetricBlock label="Outgoing" value={outgoing} title="Outgoing private messages" />
            <MetricBlock
              label="Campaign posts"
              value={scopeAccount ? campaignPosts : campaignPosts}
              tone="success"
              highlight
              highlightVariant="campaign"
              title="Successful master-list cycle posts since reset (all accounts)"
            />
            <MetricBlock
              label="Forward posts (since reset)"
              value={scopeAccount ? forwardPosts : forwardPosts}
              tone="success"
              highlight
              highlightVariant="forward"
              title="Successful interval forwards since Reset 24 Hours — cumulative, not this tick"
            />
            <MetricBlock
              label="Joined since reset"
              value={joinedToday}
              sub={joinLimit > 0
                ? `${joinedToday}/${joinLimit}${scopeAccount ? ' daily limit' : ` ${SABHI_DAILY_LIMIT}`}`
                : (scopeAccount ? 'This account' : SABHI_ACCOUNTS_COMBINED)}
              tone="success"
              title="New groups joined via automation"
            />
            {!scopeAccount && (
              <>
                <MetricBlock
                  label="Current cycle"
                  value={fleetCycle.success}
                  sub={`${fleetCycle.failed} failed · ${fleetCycle.skipped} skipped`}
                  title="Live campaign-cycle counters (campaign-mode accounts)"
                />
                <MetricBlock
                  label="Forward running"
                  value={fleetForward.running}
                  sub={`${fleetForward.sent} sent · ${fleetForward.skipped} skipped · ${fleetForward.failed} failed`}
                  title="Forwarding-mode accounts — live tick totals"
                />
              </>
            )}
          </MetricGrid>
        </>
      ) : reachView === 'campaign' ? (
        <>
          {!scopeAccount && (
            <p className="daily-stats-view-hint">
              {accountsCampaign} account{accountsCampaign === 1 ? '' : 's'} on campaign cycles
              {accountsForwarding > 0 ? ` · ${accountsForwarding} on forwarding` : ''}
            </p>
          )}
          <MetricGrid columns={4} className="daily-stats-grid">
            <MetricBlock label="Contacts" value={contacts} tone="success" title={`Unique DM contacts in this window (${SABHI_ACCOUNTS.toLowerCase()})`} />
            <MetricBlock label="Incoming" value={incoming} title="Incoming private messages" />
            <MetricBlock label="Outgoing" value={outgoing} title="Outgoing private messages" />
            <MetricBlock
              label="Campaign posts"
              value={scopeAccount ? campaignPosts : campaignPostsInMode || campaignPosts}
              tone="success"
              highlight
              highlightVariant="campaign"
              title="Successful master-list cycle posts since reset"
            />
            <MetricBlock
              label="Joined since reset"
              value={joinedToday}
              sub={joinLimit > 0
                ? `${joinedToday}/${joinLimit}${scopeAccount ? ' daily limit' : ` ${SABHI_DAILY_LIMIT}`}`
                : (scopeAccount ? 'This account' : SABHI_ACCOUNTS_COMBINED)}
              tone="success"
              title="New groups joined via automation"
            />
            {!scopeAccount && (
              <MetricBlock
                label="Current cycle"
                value={fleetCycle.success}
                sub={`${fleetCycle.failed} failed · ${fleetCycle.skipped} skipped`}
                title="Live campaign-cycle counters (this run, campaign-mode accounts)"
              />
            )}
          </MetricGrid>
        </>
      ) : (
        <>
          {!scopeAccount && (
            <p className="daily-stats-view-hint">
              {accountsForwarding} account{accountsForwarding === 1 ? '' : 's'} on forwarding
              {accountsCampaign > 0 ? ` · ${accountsCampaign} on campaign cycles` : ''}
            </p>
          )}
          <MetricGrid columns={4} className="daily-stats-grid">
            <MetricBlock
              label="Forward posts (since reset)"
              value={scopeAccount ? forwardPosts : forwardPostsInMode || forwardPosts}
              tone="success"
              highlight
              highlightVariant="forward"
              sub={!scopeAccount && fleetForward.sent > 0
                ? `this tick: ${fleetForward.sent} sent`
                : undefined}
              help={FORWARDING_METRIC_HELP.forwardPosts}
            />
            {!scopeAccount && (
              <>
                <MetricBlock
                  label="Running now"
                  value={fleetForward.running}
                  help={FORWARDING_METRIC_HELP.runningNow}
                />
                <MetricBlock
                  label="Current tick sent"
                  value={fleetForward.sent}
                  sub={`${fleetForward.skipped} skipped · ${fleetForward.failed} failed`}
                  help={FORWARDING_METRIC_HELP.currentTickSent}
                />
              </>
            )}
            {scopeAccount && (
              <MetricBlock
                label="Current tick"
                value={Number(featureRuntime(accountStates?.[scopeAccount], 'forwarding').success) || 0}
                sub={`${Number(featureRuntime(accountStates?.[scopeAccount], 'forwarding').skipped_already_posted) || 0} skipped · ${Number(featureRuntime(accountStates?.[scopeAccount], 'forwarding').failed) || 0} failed`}
                help={FORWARDING_METRIC_HELP.currentTickAccount}
              />
            )}
            <MetricBlock
              label="Joined since reset"
              value={joinedToday}
              sub={joinLimit > 0 ? `${joinedToday}/${joinLimit} limit` : undefined}
              tone="success"
              help={
                scopeAccount
                  ? FORWARDING_METRIC_HELP.joinedSinceResetAccount
                  : FORWARDING_METRIC_HELP.joinedSinceReset
              }
            />
          </MetricGrid>
        </>
      )}

      {!scopeAccount && ranked.length > 0 && (
        <details className="daily-stats-per-account">
          <summary>
            Per account · {reachView === 'forwarding' ? 'forwarding' : reachView === 'campaign' ? 'campaign' : 'all modes'}
          </summary>
          <ul className="daily-stats-account-list">
            {ranked.map(row => {
              const rowResetting = resetting === row.slot
              return (
                <li key={row.slot} className="daily-stats-account-row">
                  <span className="daily-stats-account-name">
                    {accountLabel(row.slot)}
                    <span className="daily-stats-account-mode">
                      {row.mode === 'forwarding' ? 'Fwd' : 'Cycle'}
                    </span>
                  </span>
                  <span className="daily-stats-account-metrics">
                    {reachView === 'forwarding'
                      ? `${row.forward_posts ?? 0} forward posts`
                      : reachView === 'campaign'
                        ? `${row.contacts ?? 0} contacts · ${row.incoming ?? 0} in · ${row.outgoing ?? 0} out · ${row.campaign_posts ?? row.forwarded ?? 0} posts`
                        : `${row.contacts ?? 0} contacts · ${row.campaign_posts ?? row.forwarded ?? 0} cycle · ${row.forward_posts ?? 0} forward`}
                  </span>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm daily-stats-account-reset"
                    onClick={() => handleReset('account', row.slot)}
                    disabled={!!resetting}
                    title={`Reset 24-hour stats for ${accountLabel(row.slot)} only`}
                  >
                    <ButtonContent loading={rowResetting} loadingLabel="…">
                      Reset
                    </ButtonContent>
                  </button>
                </li>
              )
            })}
          </ul>
        </details>
      )}

      <p className="daily-stats-footnote">
        {reachView === 'all'
          ? 'All combines DM stats with campaign and forwarding counts. Use Campaign cycles or Forwarding tabs for mode-specific live counters.'
          : reachView === 'forwarding'
            ? 'Forwarding: “Forward posts (since reset)” is cumulative; “Current tick sent” is the live batch only. Inbox contacts appear under Campaign cycles.'
            : 'Campaign counts master-list cycle posts. Use Accounts → Forwarding or the tab above for interval forward stats.'}
        {' '}
        {scopeAccount
          ? 'Counters reset per account; sessions and history are kept.'
          : 'Reset clears forward/campaign counters, current tick display, and join-since-reset baselines. Accounts, chats, and logs are kept.'}
      </p>

      {toast && (
        <div className="crm-toast daily-stats-toast" role="status" aria-live="polite">
          {toast}
        </div>
      )}
    </section>
  )
}
