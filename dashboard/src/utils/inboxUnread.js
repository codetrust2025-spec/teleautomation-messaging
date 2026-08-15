/** Total unread DM count across active (non-blocked) inbox only. */

export function computeInboxUnreadTotal(inboxState) {
  if (!inboxState?.slots) return 0
  let total = 0
  for (const block of Object.values(inboxState.slots)) {
    for (const c of block.conversations || []) {
      if (c.crm_blocked || c.crm_status === 'spam') continue
      total += Math.max(0, Number(c.unread_count) || 0)
    }
  }
  return total
}

export function formatUnreadBadgeCount(count) {
  const n = Math.max(0, Number(count) || 0)
  if (n <= 0) return ''
  return n > 99 ? '99+' : String(n)
}
