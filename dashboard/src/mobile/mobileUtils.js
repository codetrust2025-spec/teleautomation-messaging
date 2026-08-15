import {

  accountLabel,

  featureRuntime,

  formatPhoneDisplay,

  getAccountStatus,

  isCampaignEnabled,

  isForwardingEnabled,

  filterSlotsExcludingShutdown,

  telegramDisplayName,

} from '../utils/accountUi.js'

import { buildFleetHealthRows } from '../utils/fleetHealth.js'
import {
  includeSlot,
  sumDailyForwardPostsLoggedIn,
  sumDailyPostsSinceWindow,
} from '../utils/globalStats.js'



const AVATAR_COLORS = ['#3b82f6', '#8b5cf6', '#f97316', '#22c55e', '#ec4899', '#06b6d4']



export function avatarColor(slot) {

  const n = parseInt(String(slot).replace(/\D/g, ''), 10) || 0

  return AVATAR_COLORS[n % AVATAR_COLORS.length]

}



export function avatarInitials(slot, info) {

  const name = telegramDisplayName(info) || accountLabel(slot)

  const parts = name.replace(/[^a-zA-Z0-9\s]/g, ' ').trim().split(/\s+/).filter(Boolean)

  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()

  if (parts.length === 1 && parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase()

  return accountLabel(slot).replace(/Account\s*/i, 'A').slice(0, 2).toUpperCase()

}



export function accountStatusPillLabel(status, running) {

  if (running) return 'Running'

  if (status === 'sleeping') return 'Rest'

  if (status === 'shutdown') return 'Shutdown'

  if (status === 'rate_limited') return 'Limited'

  return 'Stopped'

}

/** Logged-in slots that are not on the shutdown list (1-week rest / removed from fleet). */
export function activeFleetSlots(state, loggedInSlots) {
  return filterSlotsExcludingShutdown(
    loggedInSlots,
    state.account_shutdown,
    state.shutdown_list,
  )
}

/** Fleet grid ordering — same active slot list used by dashboard stats. */
export function sortedFleetSlots(state, loggedInSlots) {
  return activeFleetSlots(state, loggedInSlots)
}

/** Same running signal as account list rows / start-stop buttons for a workspace mode. */
export function isAccountActiveForModeFilter(acct, slot, state, postingModes, modeFilter = 'all') {
  if (!acct || !slot) return false
  const status = getAccountStatus(
    acct,
    !!state.account_info?.[slot],
    state.account_status?.[slot],
    state.account_shutdown,
    slot,
  )
  if (modeFilter === 'campaign') {
    if (!isCampaignEnabled(state.account_states, slot, postingModes)) return false
    const camp = featureRuntime(acct, 'campaign')
    return (
      !!camp.running
      || camp.status === 'sleeping'
      || status === 'running'
      || status === 'sleeping'
    )
  }
  if (modeFilter === 'forwarding') {
    if (!isForwardingEnabled(state.account_states, slot, postingModes)) return false
    const fwd = featureRuntime(acct, 'forwarding')
    return (
      !!fwd.running
      || fwd.status === 'sleeping'
      || status === 'running'
      || status === 'sleeping'
    )
  }
  return status === 'running' || status === 'sleeping'
}



export function computeMobileStats({

  state,

  loggedInSlots,

  postingModes,

  inboxUnreadTotal,

  fleet,

  modeFilter = 'all',

}) {

  let fwdRunning = 0

  let fwdGroups = 0

  let campRunning = 0

  let runningAccounts = 0

  let restingAccounts = 0

  const fleetSlots = activeFleetSlots(state, loggedInSlots)

  for (const slot of fleetSlots) {

    const acct = state.account_states?.[slot] || {}

    const st = getAccountStatus(

      acct,

      !!state.account_info?.[slot],

      state.account_status?.[slot],

      state.account_shutdown,

      slot,

    )

    if (isForwardingEnabled(state.account_states, slot, postingModes)) {

      const ag = Number(acct.forwarding?.active_groups ?? acct.forwarding_active_groups ?? 0)

      fwdGroups += ag

      if (st === 'running' || st === 'sleeping') fwdRunning += 1

    }

    if (isCampaignEnabled(state.account_states, slot, postingModes)) {
      const camp = featureRuntime(acct, 'campaign')
      if (camp.running || camp.status === 'sleeping') campRunning += 1
    }

    if (st === 'running' || st === 'sleeping') runningAccounts += 1
    else if (st === 'idle' || st === 'stopped' || st === 'sleeping') restingAccounts += 1
  }

  const totalAccounts = fleetSlots.length
  restingAccounts = Math.max(0, totalAccounts - runningAccounts)



  const rows = buildFleetHealthRows(

    fleet.perAccount || [],

    state.account_info,

    state.daily_stats?.window,

    state.daily_stats?.reset_at ? new Date(state.daily_stats.reset_at).getTime() / 1000 : 0,

  )

  const alertCount = rows.filter(r => r.attention === 'critical' || r.attention === 'warn').length



  const progressMax = fleet.progressMax || 1

  const progressValue = fleet.progressValue || 0

  const progressPct = Math.round((progressValue / progressMax) * 100)

  const healthPercent = Math.max(

    0,

    Math.min(100, progressPct - alertCount * 8 + (fleet.runningCount > 0 ? 5 : 0)),

  )



  const postsFromDaily = sumDailyPostsSinceWindow(state, fleetSlots, {
    postingModes,
    modeFilter,
  })

  const modeEnabledCount =
    modeFilter === 'all'
      ? fleetSlots.length
      : fleetSlots.filter(slot =>
          includeSlot(modeFilter, state.account_states, postingModes, slot),
        ).length

  const displayRunning =
    modeFilter === 'campaign'
      ? campRunning
      : modeFilter === 'forwarding'
        ? fwdRunning
        : runningAccounts

  const displayResting = Math.max(0, modeEnabledCount - displayRunning)
  const postsToday = Math.max(
    Number(fleet.messagesSent24h ?? 0),
    postsFromDaily,
  )



  return {

    totalAccounts,

    runningAccounts,

    restingAccounts,

    modeEnabledCount,

    displayRunning,

    displayResting,

    activeCount: fleet.runningCount + fleet.sleepingCount,

    fwdRunning,

    fwdGroups: fwdGroups || progressMax,

    inboxNew: inboxUnreadTotal,

    campRunning,

    alertCount,

    failedCount: fleet.failed ?? 0,

    activeTasks: fleet.runningCount ?? 0,

    progressValue,

    progressMax,

    progressPct,

    healthPercent,

    messagesSent24h: postsToday,

    postsToday,

    successRate: fleet.successRate,

    tickSent: fleet.success,

    sleeping: fleet.sleepingCount > 0,

    countdown: fleet.minCountdown,

  }

}



function accountSubLabel(slot, info) {
  const base = accountLabel(slot)
  const raw = info?.phone
  if (!raw) return base
  const digits = String(raw).replace(/\D/g, '')
  const phone =
    digits.length === 12 && digits.startsWith('91')
      ? `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`
      : formatPhoneDisplay(raw)
  return `${base} · ${phone}`
}

/** Lower = higher in list (running accounts first). */
function accountListSortKey(row) {
  if (row.status === 'running') return 0
  if (row.status === 'sleeping') return 1
  if (row.status === 'rate_limited') return 2
  return 3
}

export function sortAccountsRunningFirst(rows) {
  return [...rows].sort((a, b) => {
    const ka = accountListSortKey(a)
    const kb = accountListSortKey(b)
    if (ka !== kb) return ka - kb
    return (a.displayName || '').localeCompare(b.displayName || '', undefined, { sensitivity: 'base' })
  })
}

export function accountRowsForMobile(state, loggedInSlots, postingModes, modeFilter = 'all') {

  let slots = activeFleetSlots(state, loggedInSlots)

  if (modeFilter === 'forwarding') {
    slots = slots.filter(slot =>
      isForwardingEnabled(state.account_states, slot, postingModes),
    )
  } else if (modeFilter === 'campaign') {
    slots = slots.filter(slot =>
      isCampaignEnabled(state.account_states, slot, postingModes),
    )
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
      running =
        !!camp.running
        || camp.status === 'sleeping'
        || status === 'running'
        || status === 'sleeping'
    } else if (modeFilter === 'forwarding') {
      const fwd = featureRuntime(acct, 'forwarding')
      running =
        !!fwd.running
        || fwd.status === 'sleeping'
        || status === 'running'
        || status === 'sleeping'
    }
    const pillRest =
      status === 'sleeping' || status === 'idle' || status === 'stopped'

    return {

      slot,

      info,

      status,

      displayName: telegramDisplayName(info) || accountLabel(slot),

      subLabel: accountSubLabel(slot, info),

      initials: avatarInitials(slot, info),

      color: avatarColor(slot),

      running,

      pillLabel: accountStatusPillLabel(status, running),
      pillClass: running ? 'running' : pillRest ? 'rest' : 'stopped',

    }

  })

  return sortAccountsRunningFirst(rows)

}
