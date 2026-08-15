import { accountLabel, telegramDisplayName } from './accountUi'

/**
 * Rank accounts by rolling 24h send volume (messages_sent_24h), high → low.
 * Tie-break: current-cycle success, then slot name.
 */
export function rankAccountsByPerformance(perAccount, accountInfo) {
  return [...perAccount]
    .map((row) => {
      const sent24h = row.messagesSent24h ?? 0
      const info = accountInfo?.[row.slot]
      const displayName = telegramDisplayName(info) || accountLabel(row.slot)
      const shortLabel = accountLabel(row.slot).replace('Account ', 'A')
      return {
        ...row,
        sent24h,
        displayName,
        shortLabel,
      }
    })
    .sort((a, b) => {
      if (b.sent24h !== a.sent24h) return b.sent24h - a.sent24h
      if (b.success !== a.success) return b.success - a.success
      return a.slot.localeCompare(b.slot)
    })
}
