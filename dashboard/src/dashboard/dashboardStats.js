import {
  accountLabel,
  featureRuntime,
  getAccountStatus,
  isCampaignEnabled,
  isForwardingEnabled,
  telegramDisplayName,
} from '../utils/accountUi.js'
import { buildFleetHealthRows } from '../utils/fleetHealth.js'
import { fleetDisplaySuccessRate } from '../utils/globalStats.js'
import { sortedFleetSlots } from '../mobile/mobileUtils.js'

const AVATAR_COLORS = ['#3b82f6', '#8b5cf6', '#f97316', '#22c55e', '#ec4899', '#06b6d4']

export function activeFleetSlots(state, loggedInSlots) {
  return sortedFleetSlots(state, loggedInSlots)
}

function accountInitials(slot, info) {
  const base = (telegramDisplayName(info) || accountLabel(slot))
    .replace(/[^a-zA-Z0-9\s]/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  if (base.length >= 2) return (base[0][0] + base[1][0]).toUpperCase()
  if (base.length === 1 && base[0].length >= 2) return base[0].slice(0, 2).toUpperCase()
  return accountLabel(slot).replace(/Account\s*/i, 'A').slice(0, 2).toUpperCase()
}

function accountAvatarColor(slot) {
  const n = parseInt(String(slot).replace(/\D/g, ''), 10) || 0
  return AVATAR_COLORS[n % AVATAR_COLORS.length]
}

function accountSubLabel(slot, info) {
  const name = telegramDisplayName(info) || accountLabel(slot)
  const raw = info?.phone
  if (!raw) return name
  const digits = String(raw).replace(/\D/g, '')
  const formatted =
    digits.length === 12 && digits.startsWith('91')
      ? `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`
      : String(raw)
  return `${name} · ${formatted}`
}

function accountPillLabel(status, running) {
  if (running) return 'Running'
  if (status === 'sleeping') return 'Rest'
  if (status === 'shutdown') return 'Shutdown'
  if (status === 'rate_limited') return 'Limited'
  return 'Stopped'
}

function statusSortKey(row) {
  if (row.status === 'running') return 0
  if (row.status === 'sleeping') return 1
  if (row.status === 'rate_limited') return 2
  return 3
}

function sumPostsToday(state, slots, postingModes, modeFilter) {
  const perAccount = state?.daily_stats?.per_account || {}
  let forward = 0
  let campaign = 0
  for (const slot of slots) {
    if (modeFilter === 'forwarding' && !isForwardingEnabled(state.account_states, slot, postingModes)) {
      continue
    }
    if (modeFilter === 'campaign' && !isCampaignEnabled(state.account_states, slot, postingModes)) {
      continue
    }
    const row = perAccount[slot] || {}
    forward += Number(row.forward_posts ?? 0)
    campaign += Number(row.campaign_posts ?? 0)
  }
  if (modeFilter === 'forwarding') return forward
  if (modeFilter === 'campaign') return campaign
  return forward + campaign
}

/** Rows for desktop header / account picker. */
export function accountRowsForDashboard(state, loggedInSlots, postingModes, modeFilter = 'all') {
  let slots = sortedFleetSlots(state, loggedInSlots)
  if (modeFilter === 'forwarding') {
    slots = slots.filter(slot => isForwardingEnabled(state.account_states, slot, postingModes))
  } else if (modeFilter === 'campaign') {
    slots = slots.filter(slot => isCampaignEnabled(state.account_states, slot, postingModes))
  }

  const rows = slots.map(slot => {
    const info = state.account_info?.[slot]
    const acct = state.account_states?.[slot] || {}
    const status = getAccountStatus(
      acct,
      !!info,
      state.account_status?.[slot],
      state.account_shutdown,
      slot,
    )
    let running = status === 'running' || status === 'sleeping'
    if (modeFilter === 'campaign') {
      const camp = featureRuntime(acct, 'campaign')
      running = !!camp.running || camp.status === 'sleeping' || running
    } else if (modeFilter === 'forwarding') {
      const fwd = featureRuntime(acct, 'forwarding')
      running = !!fwd.running || fwd.status === 'sleeping' || running
    }
    const resting = status === 'sleeping' || status === 'idle' || status === 'stopped'
    return {
      slot,
      info,
      status,
      displayName: telegramDisplayName(info) || accountLabel(slot),
      subLabel: accountSubLabel(slot, info),
      initials: accountInitials(slot, info),
      color: accountAvatarColor(slot),
      running,
      pillLabel: accountPillLabel(status, running),
      pillClass: running ? 'running' : resting ? 'rest' : 'stopped',
    }
  })

  return [...rows].sort((a, b) => {
    const ao = statusSortKey(a)
    const bo = statusSortKey(b)
    if (ao !== bo) return ao - bo
    return (a.displayName || '').localeCompare(b.displayName || '', undefined, { sensitivity: 'base' })
  })
}

/** Summary metrics for desktop dashboard home KPI row. */
export function buildDeskDashSummary({
  state,
  loggedInSlots,
  postingModes,
  inboxUnreadTotal,
  fleet,
  modeFilter = 'all',
}) {
  const slots = sortedFleetSlots(state, loggedInSlots)
  let fwdRunning = 0
  let fwdGroups = 0
  let campRunning = 0
  let runningAccounts = 0
  let restingAccounts = 0

  for (const slot of slots) {
    const acct = state.account_states?.[slot] || {}
    const status = getAccountStatus(
      acct,
      !!state.account_info?.[slot],
      state.account_status?.[slot],
      state.account_shutdown,
      slot,
    )
    if (isForwardingEnabled(state.account_states, slot, postingModes)) {
      const active = Number(acct.forwarding?.active_groups ?? acct.forwarding_active_groups ?? 0)
      fwdGroups += active
      if (status === 'running' || status === 'sleeping') fwdRunning += 1
    }
    if (isCampaignEnabled(state.account_states, slot, postingModes)) {
      const camp = featureRuntime(acct, 'campaign')
      if (camp.running || camp.status === 'sleeping') campRunning += 1
    }
    if (status === 'running' || status === 'sleeping') runningAccounts += 1
    else if (status === 'idle' || status === 'stopped' || status === 'sleeping') restingAccounts += 1
  }

  const totalAccounts = slots.length
  restingAccounts = Math.max(0, totalAccounts - runningAccounts)

  const resetTs = state.daily_stats?.reset_at
    ? new Date(state.daily_stats.reset_at).getTime() / 1000
    : state.daily_stats?.reset_timestamp ?? 0
  const healthRows = buildFleetHealthRows(
    fleet?.perAccount || [],
    state.account_info,
    state.daily_stats?.window,
    resetTs,
    { postingModes, accountStates: state.account_states },
  )
  const alertCount = healthRows.filter(
    row => row.attention === 'critical' || row.attention === 'warn',
  ).length

  const progressMax = fleet?.progressMax || 1
  const progressValue = fleet?.progressValue || 0
  const progressPct = progressMax > 0 ? Math.round((progressValue / progressMax) * 100) : 0
  const healthPercent = Math.max(
    0,
    Math.min(100, progressPct - alertCount * 8 + ((fleet?.runningCount ?? 0) > 0 ? 5 : 0)),
  )

  const postsToday = Math.max(
    Number(fleet?.messagesSent24h ?? 0),
    sumPostsToday(state, slots, postingModes, modeFilter),
  )

  const modeEnabledCount =
    modeFilter === 'all'
      ? slots.length
      : slots.filter(slot => {
          if (modeFilter === 'forwarding') {
            return isForwardingEnabled(state.account_states, slot, postingModes)
          }
          if (modeFilter === 'campaign') {
            return isCampaignEnabled(state.account_states, slot, postingModes)
          }
          return true
        }).length

  const displayRunning =
    modeFilter === 'campaign' ? campRunning : modeFilter === 'forwarding' ? fwdRunning : runningAccounts
  const displayResting = Math.max(0, modeEnabledCount - displayRunning)

  return {
    totalAccounts,
    runningAccounts,
    restingAccounts,
    modeEnabledCount,
    displayRunning,
    displayResting,
    activeCount: (fleet?.runningCount ?? 0) + (fleet?.sleepingCount ?? 0),
    fwdRunning,
    fwdGroups: fwdGroups || progressMax,
    inboxNew: inboxUnreadTotal ?? 0,
    campRunning,
    alertCount,
    failedCount: fleet?.failed ?? 0,
    activeTasks: fleet?.runningCount ?? 0,
    progressValue,
    progressMax,
    progressPct,
    healthPercent,
    messagesSent24h: postsToday,
    postsToday,
    successRate: fleetDisplaySuccessRate(fleet),
    tickSent: fleet?.success ?? 0,
    sleeping: (fleet?.sleepingCount ?? 0) > 0,
    countdown: fleet?.minCountdown ?? 0,
  }
}

/** @deprecated alias — desktop home imports this name */
export const computeDashboardStats = buildDeskDashSummary
