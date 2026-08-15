import { accountLabel, formatLogEventLabel, telegramDisplayName } from '../utils/accountUi.js'

function formatAgo(ts) {
  if (!ts) return 'just now'
  const t = Date.parse(ts)
  if (!Number.isFinite(t)) return 'just now'
  const sec = Math.floor((Date.now() - t) / 1000)
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

function logLine(entry) {
  const event = entry.event || ''
  const detail = (entry.summary || entry.fields?.detail || entry.msg || '').trim()
  if (event === 'SEND_FAIL') {
    const group = entry.fields?.group || entry.group_id || ''
    const err = entry.fields?.error || entry.fields?.reason || entry.reason || ''
    const parts = [formatLogEventLabel(event)]
    if (group) parts.push(String(group))
    if (err) parts.push(String(err).slice(0, 80))
    return parts.join(' · ')
  }
  return detail
}

function logIcon(level, line) {
  const l = (level || '').toLowerCase()
  const text = line.toLowerCase()
  if (l === 'error' || text.includes('fail') || text.includes('rate limit')) return '⚠'
  if (text.includes('forward') || text.includes('sent')) return '↻'
  if (text.includes('sleep') || text.includes('wait')) return '⏱'
  if (l === 'warn') return '⚠'
  return '●'
}

export function buildLiveActivityFeed(logs, accountInfo, limit = 10) {
  const items = []
  for (const entry of logs || []) {
    const line = logLine(entry)
    if (!line) continue
    const slot = entry.account_id
    const info = accountInfo?.[slot]
    const name = telegramDisplayName(info) || accountLabel(slot) || 'System'
    items.push({
      id: `${slot}-${entry.timestamp || entry.time}-${items.length}`,
      icon: logIcon(entry.level, line),
      title: line.length > 72 ? `${line.slice(0, 72)}…` : line,
      meta: name,
      ago: formatAgo(entry.timestamp || entry.time),
      level: entry.level,
    })
    if (items.length >= limit) break
  }
  return items
}

export function buildDeskAlerts({ healthRows, failedCount, alertCount }) {
  const items = []
  for (const row of healthRows || []) {
    if (!row.attention || !row.attentionHint) continue
    items.push({
      id: `health-${row.slot}`,
      type: row.attention === 'critical' ? 'error' : 'warn',
      title: row.attentionHint,
      meta: row.displayName || row.slot,
      ago: 'now',
    })
    if (items.length >= 6) break
  }
  if (failedCount > 0 && items.length < 8) {
    items.unshift({
      id: 'failed-tick',
      type: 'error',
      title: `${failedCount} failed send${failedCount === 1 ? '' : 's'} this tick`,
      meta: 'Forwarding',
      ago: 'now',
    })
  }
  if (alertCount > 0 && items.length < 8) {
    items.push({
      id: 'alerts-summary',
      type: 'warn',
      title: `${alertCount} account${alertCount === 1 ? '' : 's'} need attention`,
      meta: 'Fleet health',
      ago: 'now',
    })
  }
  return items.slice(0, 8)
}
