import React, { useState, useRef, useEffect } from 'react'
import { API, COUNTRY_CODES, SAVED_PHONES } from '../config.js'
import { ButtonContent, Spinner } from '../Loader.jsx'
import { StatusBadge } from './StatusBadge.jsx'
import { MessageEditor } from './MessageEditor.jsx'
import { PostingModePanel } from './PostingModePanel.jsx'
import {
  accountLabel,
  accountCardTitle,
  telegramDisplayName,
  telegramUsername,
  formatJoinedStats,
  formatTelegramMembershipTooltip,
  formatJoinStatsToday,
  formatMembershipScannedAt,
  isMembershipStale,
  formatMembershipAge,
  JOINS_TODAY_TOOLTIP,
  formatAccountStatusLabel,
  formatAccountMiniStatusLabel,
  formatPhoneDisplay,
  formatCountdown,
  getAccountStatus,
  getHealthLevel,
  isHeavyRateLimit,
  isCampaignEnabled,
  isForwardingEnabled,
  isSubscriptionAccount,
  accountShutdownMapForSlot,
  isAccountOnShutdown,
  accountPrimaryMode,
} from '../utils/accountUi'
import { AccountPrimaryActions } from './AccountPrimaryActions.jsx'
import { useConfirm } from '../context/ConfirmContext.jsx'
import { SubscriptionBadge } from './SubscriptionBadge.jsx'
import { Button } from './ui/Button.jsx'
import { MetricBlock, MetricGrid } from './ui/MetricBlock.jsx'
import { AccountNameEditor } from './AccountNameEditor.jsx'

function AccountCardMenu({ open, onToggle, onClose, items }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open, onClose])

  return (
    <div className="acct-v3-menu" ref={ref}>
      <button
        type="button"
        className="btn btn--ghost btn--sm acct-v3-menu-trigger"
        onClick={onToggle}
        aria-expanded={open}
        aria-haspopup="menu"
        title="More actions"
      >
        ⋯
      </button>
      {open && (
        <div className="acct-v3-menu-panel" role="menu">
          {items.map(item => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              className={`acct-v3-menu-item${item.danger ? ' acct-v3-menu-item--danger' : ''}`}
              onClick={item.onClick}
              disabled={item.disabled}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function AccountMiniCard({
  slot,
  selected,
  info,
  acctState,
  accountStatus,
  accountShutdown,
  postingModes = {},
  accountStates = {},
  switchingAccount = null,
  isSubscription = false,
  onSelect,
  onRenamed,
}) {
  const loggedIn = !!info
  const shutdownMap = accountShutdownMapForSlot(accountShutdown, slot)
  const status = getAccountStatus(acctState, loggedIn, accountStatus, shutdownMap, slot)
  const statusLabel = formatAccountMiniStatusLabel(status)
  const statusLabelFull = formatAccountStatusLabel(status)
  const tgName = telegramDisplayName(info)
  const tgUser = telegramUsername(info)
  const slotLabel = accountLabel(slot)
  const displayName = loggedIn && tgName ? tgName : (loggedIn ? slotLabel : 'Empty slot')
  const isSub = isSubscription || isSubscriptionAccount(slot, null, info)
  const membership = formatJoinedStats(info)
  const membershipStale = isMembershipStale(info)
  const phoneNumber = loggedIn ? formatPhoneDisplay(info?.phone) : ''

  const title = isSub
    ? `${accountCardTitle(slot, info)} · Subscription account`
    : accountCardTitle(slot, info)

  const groupsTooltip = membership
    ? formatTelegramMembershipTooltip(membership)
    : undefined
  const campOn = isCampaignEnabled(accountStates, slot, postingModes)
  const fwdOn = isForwardingEnabled(accountStates, slot, postingModes)

  const isSwitching = switchingAccount === slot

  function selectSlot() {
    onSelect?.(slot)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      className={`account-mini account-mini--v2${selected ? ' account-mini--selected' : ''} account-mini--${status}${status === 'shutdown' ? ' account-mini--shutdown' : ''}${isSub ? ' account-mini--subscription' : ''}${isSwitching ? ' account-mini--switching' : ''}${switchingAccount && !isSwitching ? ' account-mini--switch-pending' : ''}`}
      onClick={selectSlot}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          selectSlot()
        }
      }}
      title={title}
      aria-current={selected ? 'true' : undefined}
      aria-busy={isSwitching || undefined}
      aria-label={`${slotLabel}, ${statusLabel}${tgName ? `, ${tgName}` : ''}${membership ? `, ${membership.total} joined groups` : ''}${isSwitching ? ', switching' : ''}`}
    >
      {isSwitching && (
        <span className="account-mini-switch-overlay" aria-hidden>
          <Spinner size={18} />
        </span>
      )}
      <span className="account-mini-top">
        <span className="account-mini-top-row">
          <span className="account-mini-slot">{slotLabel}</span>
          {isSub && <SubscriptionBadge variant="icon" title="Subscription account" />}
          <span
            className={`account-mini-status-pill account-mini-status-pill--${status}`}
            title={statusLabelFull}
          >
            {statusLabel}
          </span>
        </span>
        <span className="account-mini-top-row account-mini-top-row--mode">
          {fwdOn ? (
            <span className="account-mini-mode-pill account-mini-mode-pill--forward" title="Forwarding enabled">
              Forward
            </span>
          ) : campOn ? (
            <span className="account-mini-mode-pill" title="Campaign enabled">
              Campaign
            </span>
          ) : null}
          {!campOn && !fwdOn && (
            <span className="account-mini-mode-pill account-mini-mode-pill--muted" title="No features enabled">
              Off
            </span>
          )}
        </span>
      </span>

      {loggedIn ? (
        <AccountNameEditor slot={slot} info={info} onRenamed={onRenamed} compact selected={selected} />
      ) : (
        <span className="account-mini-name" title={displayName}>{displayName}</span>
      )}

      <span
        className={`account-mini-user${tgUser ? '' : ' account-mini-user--empty'}`}
        aria-hidden={!tgUser}
      >
        {tgUser || '\u00a0'}
      </span>

      {loggedIn && phoneNumber && (
        <span className="account-mini-phone" title="Account mobile number">
          {phoneNumber}
        </span>
      )}

      {loggedIn && membership && (
        <span
          className={`account-mini-groups${membershipStale ? ' account-mini-groups--stale' : ''}`}
          title={groupsTooltip}
        >
          <span className="account-mini-groups-icon" aria-hidden>👥</span>
          {membership.total} groups
          {membershipStale && <span className="account-mini-groups-stale-dot" aria-hidden>·</span>}
        </span>
      )}

      {!loggedIn && (
        <span className="account-mini-hint">Tap to log in</span>
      )}
    </div>
  )
}

export function AccountCard({
  slot,
  label,
  info,
  isActive,
  isSubscription = false,
  acctRunning,
  onLogin,
  onLogout,
  onStart,
  onStop,
  onRefreshJoined,
  acctState,
  accountStatus,
  accountShutdown,
  forwardJob = null,
  refreshingJoined,
  accountActionLoading,
  switchingAccount,
  statsWindow: _statsWindow,
  sentInWindow: _sentInWindow,
  customMessage = '',
  onMessageSaved,
  postingModeConfig,
  postingModes = {},
  accountStates = {},
  onPostingModeUpdated,
  setupFilter = 'all',
  workspaceMode = null,
  compactSetup = false,
  onRenamed,
}) {
  const [step, setStep] = useState('idle')
  const [nameEditOpen, setNameEditOpen] = useState(false)
  const [countryCode, setCountryCode] = useState('+91')
  const [localNumber, setLocalNumber] = useState('')
  const [phone, setPhone] = useState('+91')
  const [otp, setOtp] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [menuOpen, setMenuOpen] = useState(false)
  const startLoading = accountActionLoading === `${slot}:start`
  const stopLoading = accountActionLoading === `${slot}:stop`
  const campStartLoading = accountActionLoading === `${slot}:campaign:start`
  const campStopLoading = accountActionLoading === `${slot}:campaign:stop`
  const fwdStartLoading = accountActionLoading === `${slot}:forwarding:start`
  const fwdStopLoading = accountActionLoading === `${slot}:forwarding:stop`
  const heavyLimit = isHeavyRateLimit(acctState)
  const shutdownMap = accountShutdownMapForSlot(accountShutdown, slot)
  const onShutdown = isAccountOnShutdown(shutdownMap, slot)
  const status = getAccountStatus(acctState, !!info, accountStatus, shutdownMap, slot)
  const health = getHealthLevel(acctState)
  const membership = formatJoinedStats(info)
  const membershipStale = isMembershipStale(info)
  const membershipAge = formatMembershipAge(info)
  const membershipTooltip = formatTelegramMembershipTooltip(membership)
  const joinToday = formatJoinStatsToday(acctState)
  const scannedAt = formatMembershipScannedAt(membership?.updated)
  const displayName = info ? (telegramDisplayName(info) || label) : label
  const { confirm } = useConfirm()

  function resetPhoneFields() {
    setCountryCode('+91')
    setLocalNumber('')
    setPhone('+91')
  }

  function buildPhone(code, local) {
    const c = (code || '+91').trim()
    const n = (local || '').trim().replace(/[\s-]/g, '').replace(/^0+/, '')
    if (!n) return c
    return `${c}${n}`
  }

  function applyFullPhone(full) {
    const p = full.trim().replace(/[\s-]/g, '')
    const match = COUNTRY_CODES.find(c => p.startsWith(c))
    if (match) {
      setCountryCode(match)
      setLocalNumber(p.slice(match.length))
      setPhone(p)
    } else {
      setCountryCode('+91')
      setLocalNumber(p.replace(/^\+/, ''))
      setPhone(p.startsWith('+') ? p : `+${p}`)
    }
  }

  async function loginFetch(path, body, timeoutMs = 90000) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const res = await fetch(`${API}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      let data = {}
      try {
        data = await res.json()
      } catch {
        data = {}
      }
      if (!res.ok && !data.error) {
        data.error = data.detail || `Request failed (${res.status})`
      }
      return data
    } catch (e) {
      if (e?.name === 'AbortError') {
        return { success: false, error: 'Request timed out. Check your connection and try again.' }
      }
      return { success: false, error: e?.message || 'Network error — try again.' }
    } finally {
      clearTimeout(timer)
    }
  }

  async function sendOtp() {
    const normalized = buildPhone(countryCode, localNumber)
    if (!localNumber.trim() || normalized.length < 8) {
      setError('Enter a valid phone number (e.g. 9876543210 after +91)')
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await loginFetch('/login/send-otp', { phone: normalized, slot })
      if (data.success) {
        setPhone(normalized)
        setStep('otp')
      } else setError(data.error || 'Failed to send OTP')
    } finally {
      setLoading(false)
    }
  }

  async function verifyOtp() {
    if (!otp.trim()) {
      setError('Enter the OTP code from Telegram')
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await loginFetch('/login/verify-otp', {
        code: otp.trim(),
        slot,
        workspace_mode: workspaceMode || undefined,
      })
      if (data.success) {
        setStep('idle')
        onLogin(data)
      } else setError(data.error || 'Invalid OTP')
    } finally {
      setLoading(false)
    }
  }

  async function doLogout() {
    const ok = await confirm({
      title: `Log out ${label}?`,
      message: 'This account will need phone login again to send messages.',
      confirmLabel: 'Log out',
      variant: 'warn',
    })
    if (!ok) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/login/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || !data.success) {
        setError(data.error || 'Logout failed — try again')
        return
      }
      setStep('phone')
      resetPhoneFields()
      setOtp('')
      onLogout(slot)
    } catch (e) {
      setError(e.message || 'Logout failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleStop() {
    const ok = await confirm({
      title: `Stop ${label}?`,
      message: 'The worker will stop after the current step finishes.',
      confirmLabel: 'Stop',
      cancelLabel: 'Keep running',
      variant: 'danger',
    })
    if (ok) onStop(slot)
  }

  async function doMoveToShutdown() {
    const ok = await confirm({
      title: `Move ${label} to shutdown list?`,
      message: 'The account stops posting and rests for 7 days before auto-restart. Clear it anytime from the Shutdown tab.',
      confirmLabel: 'Move to shutdown',
      variant: 'warn',
    })
    if (!ok) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/account/${slot}/shutdown`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.status === 'error') {
        setError(data.message || 'Could not move to shutdown list')
        return
      }
    } catch (e) {
      setError(e.message || 'Could not move to shutdown list')
    } finally {
      setLoading(false)
    }
  }

  const isSubAccount = isSubscription || isSubscriptionAccount(slot, null, info)

  async function handleRestart() {
    const ok = await confirm({
      title: `Restart ${label}?`,
      message: anyRunning
        ? 'Stop all features and start enabled campaign + forwarding again.'
        : 'Start all enabled features.',
      confirmLabel: 'Restart',
      variant: 'warn',
    })
    if (!ok) return
    if (anyRunning) await onStop(slot)
    onStart(slot, false)
  }

  const healthScore = acctState?.health_score != null && !Number.isNaN(Number(acctState.health_score))
    ? Math.round(Number(acctState.health_score))
    : null
  const campRt = acctState?.campaign || {}
  const fwdRt = acctState?.forwarding || {}
  const campRunning = !!(campRt.running ?? acctState?.campaign_running)
  const fwdDispatch = (
    postingModeConfig?.forwarding?.forward_dispatch
    || postingModes?.[slot]?.forwarding?.forward_dispatch
    || 'auto'
  )
  const isManualForward = fwdDispatch !== 'auto'
  const forwardCycleRunning = forwardJob?.status === 'running'
  const fwdRunning = isManualForward
    ? forwardCycleRunning
    : !!(fwdRt.running ?? acctState?.forwarding_running)
  const anyRunning = campRunning || fwdRunning || acctRunning

  const campCycle = campRt.cycle ?? acctState?.campaign_cycle ?? 0
  const campSuccess = campRt.success ?? 0
  const campFailed = campRt.failed ?? 0
  const campTotal = campRt.active_groups ?? acctState?.my_groups?.length ?? 0
  const campProcessed = campSuccess + campFailed

  const fwdCycle = fwdRt.cycle ?? acctState?.forwarding_cycle ?? 0
  const fwdSuccess = fwdRt.success ?? 0
  const fwdFailed = fwdRt.failed ?? 0
  const fwdSkipped = fwdRt.skipped_already_posted ?? 0
  const fwdTotal = fwdRt.active_groups ?? 0
  const fwdJoined = fwdRt.forward_joined_total ?? acctState?.forward_joined_total ?? 0
  const fwdProcessed = fwdSuccess + fwdFailed + fwdSkipped
  const fwdBatch = fwdRt.forward_batch ?? acctState?.forward_batch ?? 0
  const fwdBatchTotal = fwdRt.forward_batch_total ?? acctState?.forward_batch_total ?? 0

  const uiFilter = workspaceMode || setupFilter
  const showCampaignUi = uiFilter === 'all' || uiFilter === 'campaign'
  const showForwardingUi = uiFilter === 'all' || uiFilter === 'forwarding'
  const fwdCfg = postingModeConfig?.forwarding || acctState?.posting_mode_config?.forwarding || {}
  const forwardSourceType = fwdCfg.source_type === 'telegram_post' ? 'telegram_post' : 'template'
  const primaryMode = workspaceMode || accountPrimaryMode(accountStates, slot, postingModes)
  const accountMode = accountPrimaryMode(accountStates, slot, postingModes)
  const showMessageEditor = primaryMode === 'campaign'
    || (primaryMode === 'forwarding' && forwardSourceType === 'template')
  const joinsToday = joinToday?.today ?? 0
  const joinsLimit = joinToday?.limit ?? 0
  const joinsTone = joinToday?.restricted ? 'bad' : joinsLimit > 0 && joinsToday >= joinsLimit * 0.8 ? 'warn' : 'good'
  const healthTone = health === 'good' ? 'good' : health === 'warning' ? 'warn' : health === 'bad' ? 'bad' : 'neutral'
  const nextIn = acctState?.next_cycle_in > 0 ? acctState.next_cycle_in : 0
  const liveClass = status === 'running' ? 'running'
    : (status === 'sleeping' || status === 'rate_limited') ? 'waiting'
      : 'stopped'
  const currentGroup = acctState?.current_group
    ? `@${String(acctState.current_group).replace(/^@/, '')}`
    : null
  const statusSub = currentGroup && anyRunning
    ? currentGroup
    : (nextIn > 0 && (status === 'running' || status === 'sleeping'))
      ? `next in ${formatCountdown(nextIn)}`
      : null
  const hasHealth = healthScore != null && healthScore > 0
  const joinsPct = joinsLimit > 0 ? Math.round((joinsToday / joinsLimit) * 100) : null

  const metaParts = []
  if (membership) {
    metaParts.push(`${membership.total} groups`)
    metaParts.push(`${membership.groups}g / ${membership.channels}c`)
  }
  if (scannedAt) metaParts.push(`scanned ${membershipAge || scannedAt}`)
  if (membershipStale) metaParts.push('stale')
  const metaLine = metaParts.join(' · ')

  const cardClass = [
    'account-card',
    isActive ? 'account-card--active' : '',
    `account-card--${status}`,
    heavyLimit ? 'account-card--sleep' : '',
    isSubAccount ? 'account-card--subscription' : '',
  ].filter(Boolean).join(' ')

  return (
    <article className={`${cardClass} account-card--dense account-card--v3 account-card--live account-card--live-${liveClass}${compactSetup ? ' account-card--setup-compact' : ''}`}>
      {info ? (
        <>
          <div className="acct-v3-shine" aria-hidden />
          <header className="acct-v3-header">
            <div className="acct-v3-identity">
              <AccountNameEditor
                slot={slot}
                info={info}
                onRenamed={onRenamed}
                startEditing={nameEditOpen}
                onEditingChange={open => { if (!open) setNameEditOpen(false) }}
              />
              <p className="acct-v3-phone-row">
                {info.phone && <span>{formatPhoneDisplay(info.phone)}</span>}
                {isSubAccount && <SubscriptionBadge variant="dot" title="Subscription account" />}
              </p>
            </div>
            <div className="acct-v3-status-wrap">
              <StatusBadge
                status={status}
                pulse={status === 'running'}
                label={
                  status === 'sleeping' ? 'Waiting'
                    : status === 'rate_limited' ? 'Flood'
                      : undefined
                }
              />
              {statusSub && (
                <span className="acct-v3-status-sub">{statusSub}</span>
              )}
            </div>
          </header>

          <div className="acct-v3-body" onClick={e => e.stopPropagation()}>
            <MetricGrid columns={2} className="acct-v3-grid">
              {membership != null || refreshingJoined ? (
                <MetricBlock
                  className="acct-v3-cell"
                  label="On Telegram"
                  value={refreshingJoined ? '…' : membership.total}
                  tone={membershipStale ? 'warn' : 'neutral'}
                  title={membershipTooltip}
                />
              ) : null}
              {joinToday ? (
                <MetricBlock
                  className="acct-v3-cell"
                  label="Joins"
                  value={`${joinToday.today}${joinToday.limit != null ? `/${joinToday.limit}` : ''}`}
                  progress={joinsPct}
                  tone={joinsTone}
                  title={JOINS_TODAY_TOOLTIP}
                />
              ) : null}
              {showCampaignUi && (
                <MetricBlock
                  className="acct-v3-cell acct-v3-cell--feature"
                  label="Campaign"
                  value={campRunning ? 'Running' : 'Stopped'}
                  sub={campTotal > 0 ? `${campProcessed}/${campTotal} · cycle ${campCycle || '—'}` : `cycle ${campCycle || '—'}`}
                  tone={campRunning ? 'good' : 'neutral'}
                  title={`Campaign: ${campSuccess} sent · ${campFailed} failed`}
                />
              )}
              {showForwardingUi && (
                <MetricBlock
                  className="acct-v3-cell acct-v3-cell--feature"
                  label="Forwarding"
                  value={fwdRunning ? 'Running' : 'Stopped'}
                  sub={fwdTotal > 0
                    ? `${fwdProcessed}/${fwdTotal}${fwdJoined > fwdTotal ? ` · ${fwdJoined} joined` : ''}${fwdBatchTotal ? ` · B${fwdBatch}/${fwdBatchTotal}` : ''}`
                    : (fwdJoined ? `${fwdJoined} joined` : `tick ${fwdCycle || '—'}`)}
                  tone={fwdRunning ? 'good' : 'neutral'}
                  title={`Forward tick #${fwdCycle} · sent ${fwdSuccess} · skip ${fwdSkipped} · fail ${fwdFailed}`}
                />
              )}
              {hasHealth ? (
                <MetricBlock
                  className="acct-v3-cell"
                  label="Health"
                  value={`${healthScore}%`}
                  progress={healthScore}
                  tone={healthTone}
                  title={`Health score ${healthScore}%`}
                />
              ) : null}
            </MetricGrid>
            {(refreshingJoined || metaLine) && (
              <p className="acct-v3-meta">
                {refreshingJoined ? (
                  <span className="acct-v3-meta-loading"><Spinner size={10} /> Scanning…</span>
                ) : metaLine}
              </p>
            )}
          </div>

          <div className={`acct-v3-setup-flow${workspaceMode ? ` acct-v3-setup-flow--${workspaceMode}` : ''}`} onClick={e => e.stopPropagation()}>
            <AccountPrimaryActions
              slot={slot}
              postingModeConfig={postingModeConfig || acctState?.posting_mode_config}
              postingModes={postingModes}
              accountStates={accountStates}
              acctState={acctState}
              forwardJob={forwardJob}
              onShutdown={onShutdown}
              onStart={onStart}
              onStop={onStop}
              accountActionLoading={accountActionLoading}
              forcedMode={workspaceMode || undefined}
              className="acct-v3-primary-actions"
            />
            <div className="acct-v3-actions-secondary acct-v3-actions-secondary--inline">
              <Button
                variant="ghost"
                size="sm"
                className="acct-v3-btn-action acct-v3-btn-restart"
                onClick={handleRestart}
                disabled={startLoading || stopLoading || campStartLoading || fwdStartLoading}
              >
                ↻ Restart all
              </Button>
              <AccountCardMenu
                open={menuOpen}
                onToggle={() => setMenuOpen(v => !v)}
                onClose={() => setMenuOpen(false)}
                items={[
                  {
                    key: 'rename',
                    label: 'Rename profile',
                    onClick: () => {
                      setMenuOpen(false)
                      setNameEditOpen(true)
                    },
                  },
                  {
                    key: 'rescan',
                    label: refreshingJoined ? 'Scanning…' : 'Rescan membership',
                    onClick: () => { setMenuOpen(false); onRefreshJoined(slot) },
                    disabled: refreshingJoined,
                  },
                  {
                    key: 'shutdown',
                    label: onShutdown ? 'On shutdown list' : 'Move to shutdown list',
                    onClick: () => { setMenuOpen(false); doMoveToShutdown() },
                    disabled: loading || onShutdown,
                  },
                  {
                    key: 'logout',
                    label: 'Log out',
                    danger: true,
                    onClick: () => { setMenuOpen(false); doLogout() },
                    disabled: loading || anyRunning,
                  },
                ]}
              />
            </div>
            <details className="acct-setup-details" open={!compactSetup}>
              <summary className="acct-setup-details__summary">
                {workspaceMode === 'forwarding' ? 'Forward message & settings' : workspaceMode === 'campaign' ? 'Campaign message & settings' : 'Message & settings'}
                {compactSetup && (
                  <span className="acct-setup-details__hint"> — use setup tab</span>
                )}
              </summary>
              <PostingModePanel
                slot={slot}
                postingModeConfig={postingModeConfig || acctState?.posting_mode_config}
                postingModes={postingModes}
                accountStates={accountStates}
                acctRunning={anyRunning}
                onUpdated={onPostingModeUpdated}
                onStartForward={s => onStart(s, false, 'forwarding')}
                onStopForward={s => onStop(s, 'forwarding')}
                setupFilter={uiFilter === 'all' ? workspaceMode || 'all' : uiFilter}
                layout="simple"
                primaryMode={primaryMode}
              />
              {showMessageEditor && (
                <div className="acct-v3-message-editor">
                  <MessageEditor
                    slot={slot}
                    customMessage={customMessage}
                    onSaved={onMessageSaved || (() => {})}
                  />
                </div>
              )}
            </details>
          </div>
        </>
      ) : step === 'idle' ? (
        <div className="account-card-login">
          <p className="stat-hint">Not logged in</p>
          <button type="button" className="btn btn--success" onClick={() => { resetPhoneFields(); setStep('phone') }}>
            + Login
          </button>
        </div>
      ) : step === 'phone' ? (
        <div className="account-card-form" onClick={e => e.stopPropagation()}>
          <label className="field-label">Phone number</label>
          <div className="field-row">
            <select className="input input--select" value={countryCode} onChange={e => setCountryCode(e.target.value)}>
              {COUNTRY_CODES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <input
              className="input"
              type="tel"
              placeholder="9876543210"
              value={localNumber}
              onChange={e => setLocalNumber(e.target.value.replace(/\D/g, ''))}
              onKeyDown={e => e.key === 'Enter' && localNumber.trim() && sendOtp()}
              autoFocus
            />
          </div>
          <select className="input" value="" onChange={e => { if (e.target.value) applyFullPhone(e.target.value) }}>
            <option value="">Quick pick saved number…</option>
            {SAVED_PHONES.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
          {error && <p className="field-error">{error}</p>}
          <div className="btn-row">
            <button type="button" className="btn btn--primary" onClick={sendOtp} disabled={loading || !localNumber.trim()}>
              <ButtonContent loading={loading} loadingLabel="Sending…">Send OTP</ButtonContent>
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => { resetPhoneFields(); setStep('idle'); setError('') }}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="account-card-form" onClick={e => e.stopPropagation()}>
          <p className="field-hint">OTP sent to <strong>{phone}</strong></p>
          <input className="input" placeholder="Enter OTP" value={otp} onChange={e => setOtp(e.target.value)} onKeyDown={e => e.key === 'Enter' && verifyOtp()} />
          {error && <p className="field-error">{error}</p>}
          <div className="btn-row">
            <button type="button" className="btn btn--success" onClick={verifyOtp} disabled={loading || !otp}>
              <ButtonContent loading={loading} loadingLabel="Verifying…">Verify</ButtonContent>
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => { resetPhoneFields(); setStep('phone'); setError('') }}>← Back</button>
          </div>
        </div>
      )}
    </article>
  )
}
