import { accountLabel, telegramDisplayName } from './accountUi.js'

/** Hours used for posts/hour when window is since_reset or rolling 24h. */
export function statsWindowHours(statsWindow, resetTimestamp) {
  const nowSec = Date.now() / 1000
  if (statsWindow === 'since_reset' && resetTimestamp > 0) {
    return Math.max(0.25, (nowSec - resetTimestamp) / 3600)
  }
  return 24
}

export function computePostsPerHour(forwards, statsWindow, resetTimestamp) {
  const hours = statsWindowHours(statsWindow, resetTimestamp)
  return forwards / hours
}

/**
 * @returns {'ok'|'warn'|'critical'|null}
 */
export function fleetAttentionLevel(row, loggedIn) {
  const health = row.health ?? 100
  const reasons = []

  if (health < 50) reasons.push('low_health')
  else if (health < 80) reasons.push('health')

  if (loggedIn && !row.running) reasons.push('stopped')
  if (loggedIn && row.running && (row.messagesSent24h ?? 0) === 0) reasons.push('no_forwards')
  if (row.status === 'rate_limited' || row.status === 'flood_wait') reasons.push('limited')

  if (reasons.includes('low_health') || reasons.includes('stopped')) return 'critical'
  if (reasons.length > 0) return 'warn'
  return null
}

export function fleetAttentionLabel(level, row, loggedIn) {
  if (!level) return null
  const parts = []
  const health = row.health ?? 100
  if (health < 50) parts.push('Low health')
  else if (health < 80) parts.push('Health recovering')
  if (loggedIn && !row.running) parts.push('Worker stopped')
  if (loggedIn && row.running && (row.messagesSent24h ?? 0) === 0) parts.push('No forwards yet')
  if (row.status === 'rate_limited' || row.status === 'flood_wait') parts.push('Rate limited')
  return parts.join(' · ') || 'Needs attention'
}

export function buildFleetHealthRows(perAccount, accountInfo, statsWindow, resetTimestamp) {
  const hours = statsWindowHours(statsWindow, resetTimestamp)
  const windowLabel = statsWindow === 'since_reset' ? 'since reset' : '24h'

  return perAccount.map((row) => {
    const info = accountInfo?.[row.slot]
    const loggedIn = !!info
    const forwards = row.messagesSent24h ?? 0
    const rate = computePostsPerHour(forwards, statsWindow, resetTimestamp)
    const attention = fleetAttentionLevel(row, loggedIn)
    return {
      ...row,
      loggedIn,
      displayName: telegramDisplayName(info) || '—',
      shortLabel: accountLabel(row.slot).replace('Account ', 'A'),
      forwards,
      postsPerHour: rate,
      windowLabel,
      windowHours: hours,
      attention,
      attentionHint: fleetAttentionLabel(attention, row, loggedIn),
    }
  })
}

export function sortFleetHealthRows(rows) {
  const order = { critical: 0, warn: 1, ok: 2 }
  return [...rows].sort((a, b) => {
    const ao = a.attention ? order[a.attention] ?? 1 : 2
    const bo = b.attention ? order[b.attention] ?? 1 : 2
    if (ao !== bo) return ao - bo
    return (a.postsPerHour ?? 0) - (b.postsPerHour ?? 0)
  })
}

export function formatPostsPerHour(rate) {
  if (!Number.isFinite(rate) || rate <= 0) return '0'
  if (rate >= 10) return rate.toFixed(1)
  return rate.toFixed(2)
}
