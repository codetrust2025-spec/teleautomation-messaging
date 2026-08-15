/** Shared account / status helpers for dashboard UI */

import {
  formatIstAge,
  formatIstLogTime,
  formatIstShort,
  parseInstant,
} from './istTime.js'

export const RUN_UI = {
  text: '#22c55e',
  border: '#166534',
  borderActive: '#22c55e',
  bg: '#14251a',
  bgActive: '#1a2e22',
  badge: '#16a34a',
}

export const SLEEP_UI = {
  text: '#fbbf24',
  border: '#713f12',
  borderActive: '#b45309',
  bg: '#1a1814',
  bgActive: '#1f1a14',
  badge: '#b45309',
}

export function formatDurationShort(seconds) {
  const s = Math.max(0, Number(seconds) || 0)
  if (s >= 86400) return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
  if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${s}s`
}

export function isHeavyRateLimit(acctState) {
  return !!(acctState?.heavy_rate_limit || (
    acctState?.status === 'flood_wait' &&
    (acctState?.notification || '').toLowerCase().includes('heavy rate limit')
  ))
}

export function sleepSummary(acctState) {
  if (!isHeavyRateLimit(acctState)) return null
  const left = acctState?.next_cycle_in > 0 ? formatDurationShort(acctState.next_cycle_in) : null
  return left ? `Sleeping · ~${left} left` : 'Sleeping (rate limited)'
}

export function accountLabel(slot) {
  const m = String(slot).match(/^account(\d+)$/i)
  return m ? `Account ${m[1]}` : slot
}

/** Inbox UI: which logged-in Telegram account owns this chat (custom or Telegram name). */
export function inboxAccountOwnerName(slot, accountInfo) {
  if (!slot) return ''
  const info = accountInfo?.[slot]
  return telegramDisplayName(info) || accountLabel(slot)
}

/** Telegram name from login (ignores dashboard display_name override). */
export function telegramLegalName(info) {
  if (!info) return null
  const name = String(info.name || '').trim()
  const first = String(info.first_name || '').trim()
  const last = String(info.last_name || '').trim()
  const full = name || [first, last].filter(Boolean).join(' ')
  const user = String(info.username || '').trim().replace(/^@/, '')
  if (full) return full
  if (user) return `@${user}`
  return null
}

/** Profile label in UI — custom display_name if set, else Telegram name. */
export function telegramDisplayName(info) {
  if (!info) return null
  const custom = String(info.display_name || '').trim()
  if (custom) return custom
  return telegramLegalName(info)
}

/** @username line for mini cards (null if no username). */
export function telegramUsername(info) {
  if (!info) return null
  const user = String(info.username || '').trim().replace(/^@/, '')
  return user ? `@${user}` : null
}

/** Tooltip / title for an account card. */
export function accountCardTitle(slot, info) {
  const label = accountLabel(slot)
  const tg = telegramDisplayName(info)
  const user = telegramUsername(info)
  const phone = formatPhoneDisplay(info?.phone)
  const phoneBit = phone ? ` · ${phone}` : ''
  if (!tg) return `${label}${phoneBit}`
  if (user && tg !== user && !tg.includes(user)) {
    return `${label} — ${tg} (${user})${phoneBit}`
  }
  return `${label} — ${tg}${phoneBit}`
}

export function formatJoinedStats(info) {
  if (!info || info.joined_total == null || info.joined_total === undefined) return null
  const total = Number(info.joined_total) || 0
  const groups = Number(info.joined_groups) || 0
  const channels = Number(info.joined_channels) || 0
  return { total, groups, channels, updated: info.joined_updated_at || '' }
}

/** @deprecated alias — same as formatJoinedStats */
export const formatTelegramMembership = formatJoinedStats

export const TELEGRAM_MEMBERSHIP_TOOLTIP =
  'How many chats this account belongs to on Telegram (from a dialog scan). This is your real Telegram membership—not the upload list the bot posts to.'

export const JOINS_TODAY_TOOLTIP =
  'New groups this bot joined today via automation. Resets at IST (India) midnight and is rate-limited separately from Telegram membership.'

/** Cycle stat tiles on the account detail card. */
export const CYCLE_METRIC_SENT_TOOLTIP =
  'Messages posted successfully in the current cycle (resets when a new cycle starts).'

export const CYCLE_METRIC_FAILED_TOOLTIP =
  'Groups where posting failed in the current cycle (rate limits, blocks, errors).'

export const CYCLE_METRIC_SKIPPED_TOOLTIP =
  'Skipped this cycle because your message is already visible in recent chat history.'

export const CYCLE_METRIC_LIST_TOOLTIP =
  'Groups from your uploaded master list assigned to this account for posting. The bot cycles through these targets—not the same as “On Telegram” membership below.'

function formatScannedAt(iso) {
  if (!iso || !parseInstant(iso)) return null
  const label = formatIstShort(iso)
  return label === '—' ? null : label
}

export { formatScannedAt as formatMembershipScannedAt }

export function formatTelegramMembershipTooltip(membership) {
  if (!membership) return TELEGRAM_MEMBERSHIP_TOOLTIP
  const parts = [`${membership.groups} groups`, `${membership.channels} channels`]
  const scanned = formatScannedAt(membership.updated)
  if (scanned) parts.push(`scanned ${scanned}`)
  return `${TELEGRAM_MEMBERSHIP_TOOLTIP}\n\n${parts.join(' · ')}`
}

export function formatJoinStatsToday(acctState) {
  const js = acctState?.join_stats
  if (!js) return null
  const today = Number(js.joins_today) || 0
  const limit = js.joins_daily_limit != null ? Number(js.joins_daily_limit) : null
  return {
    today,
    limit: limit != null && !Number.isNaN(limit) ? limit : null,
    restricted: !!js.restriction_active,
  }
}

const MEMBERSHIP_STALE_MS = 10 * 60 * 1000

function parseMembershipUpdatedAt(raw) {
  return parseInstant(raw)
}

/** True when On Telegram scan is older than 10 minutes (or never run). */
export function isMembershipStale(info, thresholdMs = MEMBERSHIP_STALE_MS) {
  if (!info?.phone) return false
  if (info.joined_total == null || info.joined_total === undefined) return true
  if (info.membership_stale === true) return true
  const updated = parseMembershipUpdatedAt(info.joined_updated_at)
  if (!updated) return true
  return Date.now() - updated.getTime() > thresholdMs
}

export function formatMembershipAge(info) {
  return formatIstAge(info?.joined_updated_at)
}

/** Matches backend classify_account_info — manual list + Telegram Premium only. */
export function detectSubscriptionFromInfo(info) {
  if (!info || !info.phone) return false
  if (info.is_subscription === true) return true
  if (info.telegram_premium === true) return true
  return false
}

/** Manual list + API list + per-account info flags. */
export function isSubscriptionAccount(slot, subscriptionSlots, accountInfo) {
  if (!slot) return false
  if (Array.isArray(subscriptionSlots) && subscriptionSlots.includes(slot)) return true
  const info = accountInfo?.[slot] ?? accountInfo
  return detectSubscriptionFromInfo(info)
}

export function filterAccountsByRole(slots, subscriptionSlots, accountInfo, role) {
  if (role === 'all') return slots
  if (role === 'subscription') {
    return slots.filter(s => isSubscriptionAccount(s, subscriptionSlots, accountInfo))
  }
  if (role === 'posting') {
    return slots.filter(s => !isSubscriptionAccount(s, subscriptionSlots, accountInfo))
  }
  return slots
}

export function sortAccountSlots(slots) {
  return [...slots].sort((a, b) => {
    const na = parseInt(String(a).replace(/\D/g, ''), 10) || 0
    const nb = parseInt(String(b).replace(/\D/g, ''), 10) || 0
    return na - nb
  })
}

export function isAccountLoggedIn(accountInfo, slot) {
  const info = accountInfo?.[slot]
  return !!(info && (info.phone || info.user_id))
}

/** Slots with a saved Telegram session (shown in the account grid). */
export function getLoggedInSlots(slots, accountInfo) {
  return sortAccountSlots(slots.filter(s => isAccountLoggedIn(accountInfo, s)))
}

/** First configured slot with no login — for “Add account”. */
export function getNextAvailableSlot(slots, accountInfo) {
  return sortAccountSlots(slots).find(s => !isAccountLoggedIn(accountInfo, s)) ?? null
}

export function getAccountSlots(state, configuredSlots) {
  const fromApi = Array.isArray(state?.account_slots) ? state.account_slots : []
  const extra = Array.isArray(configuredSlots) ? configuredSlots : []
  const merged = [...new Set([...fromApi, ...extra])]
  return sortAccountSlots(merged)
}

export function sortAccountsForDisplay(slots, accountStates, accountInfo) {
  const rank = (slot) => {
    const acct = accountStates?.[slot]
    if (isHeavyRateLimit(acct)) return 3
    if (acct?.running) return 0
    if (accountInfo?.[slot]) return 1
    return 2
  }
  const slotNum = (slot) => parseInt(String(slot).replace(/\D/g, ''), 10) || 0
  return [...slots].sort((a, b) => {
    const d = rank(a) - rank(b)
    return d !== 0 ? d : slotNum(a) - slotNum(b)
  })
}

export function isAccountOnShutdown(accountShutdown, slot) {
  const info = accountShutdown?.[slot]
  return !!(info && info.active)
}

/** True when slot is on the 1-week auto-rest list (UI or backend). */
export function isSlotOnShutdownList(accountShutdown, shutdownList, slot) {
  if (!slot) return false
  if (isAccountOnShutdown(accountShutdown, slot)) return true
  return !!(shutdownList && shutdownList[slot])
}

/** Normalize per-slot shutdown object or full slot→info map for status helpers. */
export function accountShutdownMapForSlot(accountShutdown, slot) {
  if (!accountShutdown || !slot) return {}
  if (accountShutdown.active !== undefined) {
    return { [slot]: accountShutdown }
  }
  return accountShutdown
}

export function filterSlotsExcludingShutdown(slots, accountShutdown, shutdownList) {
  return (slots || []).filter(
    slot => !isSlotOnShutdownList(accountShutdown, shutdownList, slot),
  )
}

/** running | sleeping | rate_limited | stopped | idle | shutdown */
export function getAccountStatus(acctState, loggedIn, accountStatus, accountShutdown, slot) {
  if (slot && isAccountOnShutdown(accountShutdown, slot)) return 'shutdown'
  if (!loggedIn) return 'idle'
  const lifecycle = accountStatus?.lifecycle
  if (lifecycle === 'ERROR') return 'rate_limited'
  if (lifecycle === 'SLEEPING' || isHeavyRateLimit(acctState)) return 'sleeping'
  if (!acctState) return lifecycle === 'RUNNING' ? 'running' : 'stopped'
  if (acctState.status === 'flood_wait') return 'rate_limited'
  if (
    lifecycle === 'RUNNING'
    || acctState.running
    || acctState.campaign_running
    || acctState.forwarding_running
    || acctState.campaign?.running
    || acctState.forwarding?.running
  ) {
    return 'running'
  }
  return 'stopped'
}

const STATUS_LABELS = {
  running: 'Running',
  sleeping: 'Sleeping',
  rate_limited: 'Rate limited',
  stopped: 'Stopped',
  idle: 'Not logged in',
  shutdown: 'Shutdown (1 week)',
}

export function formatAccountStatusLabel(status) {
  return STATUS_LABELS[status] || 'Unknown'
}

/** Short labels for account grid mini cards (narrow columns). */
const MINI_STATUS_LABELS = {
  running: 'Run',
  sleeping: 'Wait',
  rate_limited: 'Flood',
  stopped: 'Stop',
  idle: 'Off',
  shutdown: 'Shutdown',
}

export function formatAccountMiniStatusLabel(status) {
  return MINI_STATUS_LABELS[status] || formatAccountStatusLabel(status)
}

/** Compact lines for sidebar mini cards. */
export function formatJoinedStatsLine(info, acctState) {
  const membership = formatJoinedStats(info)
  if (!membership) return null
  const parts = [
    `${membership.total} on Telegram`,
    `${membership.groups} groups · ${membership.channels} channels`,
  ]
  const scanned = formatScannedAt(membership.updated)
  if (scanned) parts.push(`scanned ${scanned}`)
  const joinToday = formatJoinStatsToday(acctState)
  if (joinToday) {
    const cap = joinToday.limit != null ? `/${joinToday.limit}` : ''
    parts.push(`${joinToday.today}${cap} joins today`)
  }
  return parts
}

export function formatQueueStatus(accountStatus) {
  if (!accountStatus) return null
  const depth = accountStatus.queue_depth ?? 0
  const max = accountStatus.queue_max_size
  if (depth <= 0 && !accountStatus.queue_processing && !accountStatus.queue_high_watermark) return null
  const proc = accountStatus.queue_processing ? ' · sending' : ''
  const cap = max ? `/${max}` : ''
  const warn = accountStatus.queue_high_watermark ? ' ⚠' : ''
  return `Queue: ${depth}${cap}${proc}${warn}`
}

export function formatPhoneDisplay(phone) {
  if (!phone) return ''
  const p = String(phone).trim()
  return p.startsWith('+') ? p : `+${p}`
}

/** good | warning | bad | unknown */
export function getHealthLevel(acctState) {
  if (!acctState) return 'unknown'
  const h = acctState.health_score
  if (h != null && !Number.isNaN(Number(h))) {
    const n = Number(h)
    if (n <= 0) return 'unknown'
    if (n >= 70) return 'good'
    if (n >= 40) return 'warning'
    return 'bad'
  }
  if (isHeavyRateLimit(acctState)) return 'bad'
  if (acctState.running && (acctState.flood_streak || 0) > 2) return 'warning'
  if (acctState.running) return 'good'
  return 'unknown'
}

export function formatLogTime(time) {
  return formatIstLogTime(time)
}

/** Human-readable labels for structured log event codes (LogPanel, live feed). */
export const LOG_EVENT_LABELS = {
  SEND_FAIL: 'Send failed',
  SEND_SUCCESS: 'Sent',
  JOIN_FAIL: 'Join failed',
  JOIN_SUCCESS: 'Joined',
  JOIN_ATTEMPT: 'Joining',
  JOIN_SKIP: 'Join skipped',
  SKIP: 'Skipped',
  FLOOD_WAIT: 'Flood wait',
  CYCLE_START: 'Cycle start',
  CYCLE_END: 'Cycle end',
  CYCLE_RESUME: 'Cycle resume',
  CYCLE_ERROR: 'Cycle error',
  RETRY_SCHEDULED: 'Retry scheduled',
  ACCOUNT_SLEEP: 'Account sleep',
  WORKER_STOP: 'Worker stopped',
  SESSION_RECONNECT: 'Reconnecting',
  TELEGRAM_CONNECTED: 'Connected',
  MSG_VARIANT_READY: 'Message ready',
  GROUP_SOURCE_EMPTY: 'No groups',
  WAIT: 'Waiting',
}

export function formatLogEventLabel(event) {
  const code = String(event || '').trim()
  if (!code) return ''
  if (LOG_EVENT_LABELS[code]) return LOG_EVENT_LABELS[code]
  return code.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export function formatCountdown(seconds) {
  const s = Math.max(0, Number(seconds) || 0)
  if (s >= 60) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
  return `${s}s`
}

/** Backend profile labels for tuned accounts (account7/8). */
export function accountProfileHint(slot) {
  const hints = {
    account7: 'Balanced',
    account8: 'Safe',
  }
  return hints[slot] || null
}

/** Raw enabled flags (may be stale if both were true in old data). */
function rawCampaignEnabled(accountStates, slot, postingModes) {
  const cfg = postingModes?.[slot]
  if (cfg && typeof cfg.campaign_enabled === 'boolean') return cfg.campaign_enabled
  const label = accountStates?.[slot]?.posting_mode || cfg?.mode || 'campaign'
  return label === 'campaign' || label === 'both'
}

function rawForwardingEnabled(accountStates, slot, postingModes) {
  const cfg = postingModes?.[slot]
  if (cfg && typeof cfg.forwarding_enabled === 'boolean') return cfg.forwarding_enabled
  const label = accountStates?.[slot]?.posting_mode || cfg?.mode || 'campaign'
  return label === 'forwarding' || label === 'both'
}

/** At most one feature on per account (forwarding wins if legacy data had both). */
export function isCampaignEnabled(accountStates, slot, postingModes) {
  const c = rawCampaignEnabled(accountStates, slot, postingModes)
  const f = rawForwardingEnabled(accountStates, slot, postingModes)
  if (c && f) return false
  return c
}

export function isForwardingEnabled(accountStates, slot, postingModes) {
  const c = rawCampaignEnabled(accountStates, slot, postingModes)
  const f = rawForwardingEnabled(accountStates, slot, postingModes)
  if (c && f) return true
  return f
}

/** Per-slot posting mode for fleet filters and stats views (legacy string). */
export function postingModeForSlot(accountStates, slot, postingModes) {
  const c = isCampaignEnabled(accountStates, slot, postingModes)
  const f = isForwardingEnabled(accountStates, slot, postingModes)
  if (f) return 'forwarding'
  if (c) return 'campaign'
  return 'none'
}

export function featureRuntime(acctState, feature) {
  const block = acctState?.[feature]
  if (block && typeof block === 'object') return block
  if (feature === 'campaign') {
    return {
      running: false,
      cycle: acctState?.cycle ?? 0,
      success: acctState?.success ?? 0,
      failed: acctState?.failed ?? 0,
      skipped_already_posted: acctState?.skipped_already_posted ?? 0,
      active_groups: acctState?.my_groups?.length ?? acctState?.active_groups ?? 0,
      status: acctState?.status ?? 'stopped',
    }
  }
  const fwd = acctState?.forwarding
  return {
    running: acctState?.forwarding_running ?? fwd?.running ?? false,
    cycle: acctState?.forwarding_cycle ?? fwd?.cycle ?? 0,
    success: fwd?.success ?? acctState?.forwarding_success ?? 0,
    failed: fwd?.failed ?? acctState?.forwarding_failed ?? 0,
    skipped_already_posted: fwd?.skipped_already_posted ?? acctState?.forwarding_skipped_already_posted ?? 0,
    active_groups: fwd?.active_groups ?? acctState?.forwarding_active_groups ?? acctState?.active_groups ?? 0,
    status: acctState?.forwarding_status ?? fwd?.status ?? acctState?.status ?? 'stopped',
    forward_batch: acctState?.forward_batch ?? fwd?.forward_batch ?? 0,
    forward_batch_total: acctState?.forward_batch_total ?? fwd?.forward_batch_total ?? 0,
    forward_joined_total: acctState?.forward_joined_total ?? fwd?.forward_joined_total ?? 0,
  }
}

/** Campaign | forwarding | off — for simplified setup UI. */
export function accountPrimaryMode(accountStates, slot, postingModes) {
  const forwardingOn = isForwardingEnabled(accountStates, slot, postingModes)
  if (forwardingOn) return 'forwarding'
  const campaignOn = isCampaignEnabled(accountStates, slot, postingModes)
  if (campaignOn) return 'campaign'
  return 'off'
}

/** Setup / stats UI view when Accounts filter is All vs Campaign vs Forwarding. */
export function setupViewForAccountsFilter(
  accountsModeFilter,
  slot,
  accountStates,
  postingModes,
) {
  if (accountsModeFilter === 'forwarding' || accountsModeFilter === 'campaign') {
    return accountsModeFilter
  }
  if (slot) return postingModeForSlot(accountStates, slot, postingModes)
  return 'all'
}
