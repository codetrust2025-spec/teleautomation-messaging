import {
  featureRuntime,
  getAccountStatus,
  isCampaignEnabled,
  isForwardingEnabled,
} from './accountUi.js'
import {
  activeFleetSlots,
  isAccountActiveForModeFilter,
} from '../mobile/mobileUtils.js'
import { WORKSPACE_CAMPAIGN, WORKSPACE_FLEET, WORKSPACE_FORWARDING } from './workspaceMode.js'

export function getDashboardModeFilter(workspaceMode) {
  if (workspaceMode === WORKSPACE_CAMPAIGN) return 'campaign'
  if (workspaceMode === WORKSPACE_FORWARDING) return 'forwarding'
  return 'all'
}

export function getDashboardModeConfig(workspaceMode) {
  const isCampaign = workspaceMode === WORKSPACE_CAMPAIGN
  const isForwarding = workspaceMode === WORKSPACE_FORWARDING
  const feature = isCampaign ? 'campaign' : 'forwarding'

  return {
    modeFilter: getDashboardModeFilter(workspaceMode),
    feature,
    isCampaign,
    isForwarding,
    isFleet: !isCampaign && !isForwarding,
    overviewTitle: isCampaign
      ? 'Campaign overview'
      : isForwarding
        ? 'Forwarding overview'
        : 'Fleet overview',
    performanceTitle: isCampaign
      ? 'Campaign performance'
      : isForwarding
        ? 'Forwarding performance'
        : 'Performance overview',
    reachTitle: isCampaign
      ? 'Today reach (Campaign)'
      : isForwarding
        ? 'Today reach (Forwarding)'
        : 'Today reach',
    postsTodayLabel: isCampaign ? 'Campaign posts' : 'Forward posts',
    postsKpiLabel: isCampaign ? 'Campaign posts' : 'Posts today',
    runningKpiLabel: isCampaign ? 'Campaigns running' : 'Forwarding active',
    runningNowLabel: isCampaign ? 'Campaigns running' : 'Forwarding now',
    tickFootLabel: isCampaign ? 'Campaign tick' : 'Forward tick',
    startLabel: isCampaign ? '▶ Start campaign' : '▶ Start forwarding',
    stopLabel: isCampaign ? '■ Stop campaign' : '■ Stop forwarding',
    bulkLabel: isCampaign ? 'Campaign setup' : 'Bulk message',
    highlightKpi: isCampaign ? 'campaign' : isForwarding ? 'forward' : null,
  }
}

export function filterSlotsForWorkspaceMode(slots, state, postingModes, workspaceMode) {
  const accountStates = state.account_states || {}
  const modeFilter = getDashboardModeFilter(workspaceMode)
  if (modeFilter === 'forwarding') {
    return slots.filter(slot => isForwardingEnabled(accountStates, slot, postingModes))
  }
  if (modeFilter === 'campaign') {
    return slots.filter(slot => isCampaignEnabled(accountStates, slot, postingModes))
  }
  return slots
}

export function isAccountRunningForWorkspace(acct, slot, state, postingModes, workspaceMode) {
  return isAccountActiveForModeFilter(
    acct,
    slot,
    state,
    postingModes,
    getDashboardModeFilter(workspaceMode),
  )
}

export function fleetWorkspaceAnyRunning(loggedInSlots, state, postingModes, workspaceMode, fleet) {
  const modeFilter = getDashboardModeFilter(workspaceMode)
  const slots = filterSlotsForWorkspaceMode(
    activeFleetSlots(state, loggedInSlots),
    state,
    postingModes,
    workspaceMode,
  )
  if (
    slots.some(slot =>
      isAccountActiveForModeFilter(
        state.account_states?.[slot],
        slot,
        state,
        postingModes,
        modeFilter,
      ),
    )
  ) {
    return true
  }
  const runningCount = Number(fleet?.runningCount ?? 0)
  const sleepingCount = Number(fleet?.sleepingCount ?? 0)
  if (modeFilter === 'forwarding' || modeFilter === 'campaign') {
    return runningCount > 0 || sleepingCount > 0
  }
  return runningCount > 0 || sleepingCount > 0
}

/** True if any logged-in account has forwarding or campaign work running/sleeping. */
export function fleetAnyProcessRunning(loggedInSlots, state, postingModes) {
  const fleetSlots = activeFleetSlots(state, loggedInSlots)
  return fleetSlots.some(slot => {
    const acct = state.account_states?.[slot]
    if (!acct) return false
    const status = getAccountStatus(
      acct,
      !!state.account_info?.[slot],
      state.account_status?.[slot],
      state.account_shutdown,
      slot,
    )
    if (status === 'running' || status === 'sleeping') return true
    const fwd = featureRuntime(acct, 'forwarding')
    const camp = featureRuntime(acct, 'campaign')
    return (
      !!fwd.running
      || fwd.status === 'sleeping'
      || !!camp.running
      || camp.status === 'sleeping'
    )
  })
}

/**
 * One-time bootstrap: if the saved workspace has zero enabled accounts, pick one that does.
 * Does not override a deliberate user tab switch while another mode is running.
 */
export function resolveWorkspaceSync(workspaceMode, loggedInSlots, state, postingModes) {
  if (workspaceMode === WORKSPACE_FLEET) return workspaceMode
  const fleetSlots = activeFleetSlots(state, loggedInSlots)
  const fwdSlots = filterSlotsForWorkspaceMode(
    fleetSlots,
    state,
    postingModes,
    WORKSPACE_FORWARDING,
  )
  const campSlots = filterSlotsForWorkspaceMode(
    fleetSlots,
    state,
    postingModes,
    WORKSPACE_CAMPAIGN,
  )

  const currentSlots =
    workspaceMode === WORKSPACE_CAMPAIGN ? campSlots : fwdSlots
  if (currentSlots.length > 0) return workspaceMode

  if (fwdSlots.length > 0) return WORKSPACE_FORWARDING
  if (campSlots.length > 0) return WORKSPACE_CAMPAIGN
  return workspaceMode
}

export function fleetWorkspaceCanStartMore(loggedInSlots, state, postingModes, workspaceMode) {
  const modeFilter = getDashboardModeFilter(workspaceMode)
  const slots = filterSlotsForWorkspaceMode(
    activeFleetSlots(state, loggedInSlots),
    state,
    postingModes,
    workspaceMode,
  )
  return slots.some(
    slot =>
      !isAccountActiveForModeFilter(
        state.account_states?.[slot],
        slot,
        state,
        postingModes,
        modeFilter,
      ),
  )
}
