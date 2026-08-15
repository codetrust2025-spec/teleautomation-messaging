import {
  formatIstDateTime,
  formatIstTime,
  IST_LOCALE,
  IST_TIMEZONE,
  istDayKey,
  parseInstant,
} from './istTime.js'

export function formatInboxTime(iso) {
  if (!iso) return ''
  const d = parseInstant(iso)
  if (!d) return ''
  if (istDayKey(d) === istDayKey()) {
    return formatIstTime(d, { hour: '2-digit', minute: '2-digit', second: undefined })
  }
  return formatIstDateTime(d, { year: undefined })
}

/** Compact time for chat list rows (Telegram-style). */
export function formatInboxListTime(iso) {
  if (!iso) return ''
  const d = parseInstant(iso)
  if (!d) return ''
  const day = istDayKey(d)
  const today = istDayKey()
  if (day === today) {
    return formatIstTime(d, { hour: 'numeric', minute: '2-digit', second: undefined, hour12: true })
  }
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)
  if (day === istDayKey(yesterday)) return 'Yesterday'
  const days = (Date.now() - d.getTime()) / 86400000
  if (days < 7) {
    return d.toLocaleDateString(IST_LOCALE, { weekday: 'short', timeZone: IST_TIMEZONE })
  }
  return d.toLocaleDateString(IST_LOCALE, {
    month: 'short',
    day: 'numeric',
    timeZone: IST_TIMEZONE,
  })
}

export const LIVE_EVENTS = new Set([
  'new_message',
  'reply_sent',
  'outgoing_message',
  'message_read',
  'message_status',
  'message_edited',
  'message_deleted',
])

/** Telegram allows editing own messages for ~48 hours. */
export const INBOX_MESSAGE_EDIT_WINDOW_MS = 48 * 60 * 60 * 1000

export function canEditOutboundMessage(m, { blocked = false } = {}) {
  if (!m || m.direction !== 'out' || blocked) return false
  const id = String(m.id ?? '')
  if (id.startsWith('pending-')) return false
  const status = String(m.status || '').toLowerCase()
  if (status === 'failed' || status === 'sending' || status === 'editing') return false
  const t = parseInstant(m.timestamp)
  if (t && Date.now() - t.getTime() > INBOX_MESSAGE_EDIT_WINDOW_MS) return false
  if (m.media || m.media_type) return false
  const text = (m.text || '').trim()
  return Boolean(text)
}

export function canDeleteOutboundMessage(m, { blocked = false } = {}) {
  if (!m || m.direction !== 'out' || blocked) return false
  const id = String(m.id ?? '')
  if (id.startsWith('pending-')) return false
  const status = String(m.status || '').toLowerCase()
  if (status === 'failed' || status === 'sending') return false
  return true
}

export function removeMessageById(prev, messageId) {
  const mid = Number(messageId)
  return (prev || []).filter(m => Number(m.id) !== mid)
}

export function slotTag(slot) {
  const m = String(slot).match(/^account(\d+)$/i)
  return m ? `A${m[1]}` : slot
}

export function sameUser(a, b) {
  return Number(a) === Number(b)
}

export function isUserNearBottom(el, thresholdPx = 80) {
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= thresholdPx
}

function messageSortKey(m) {
  const t = parseInstant(m?.timestamp)
  if (t) return t.getTime()
  const id = Number(m?.telegram_id ?? m?.id)
  return Number.isFinite(id) ? id : 0
}

function dedupeKey(m) {
  if (m?.id != null) return `id:${m.id}`
  if (m?.telegram_id != null) return `tg:${m.telegram_id}`
  return null
}

export function mergeMessageLists(incoming, prev) {
  const map = new Map()
  for (const m of prev || []) {
    const k = dedupeKey(m)
    if (k) map.set(k, m)
  }
  for (const m of incoming || []) {
    const k = dedupeKey(m)
    if (k) map.set(k, m)
    else map.set(`row:${map.size}`, m)
  }
  return [...map.values()].sort((a, b) => messageSortKey(a) - messageSortKey(b))
}

export function oldestTelegramMessageId(messages) {
  let min = null
  for (const m of messages || []) {
    const raw = m?.telegram_id ?? m?.message_id ?? m?.id
    if (raw == null || String(raw).startsWith('pending-')) continue
    const n = Number(raw)
    if (!Number.isFinite(n)) continue
    if (min == null || n < min) min = n
  }
  return min
}

export function replacePendingMessage(prev, pendingId, message) {
  return (prev || []).map(m => (m.id === pendingId ? { ...m, ...message, id: message.id ?? m.id } : m))
}

export function applyReadUpTo(prev, maxId) {
  const max = Number(maxId)
  if (!Number.isFinite(max)) return prev || []
  return (prev || []).map(m => {
    if (m.direction !== 'out') return m
    const tid = Number(m.telegram_id ?? m.message_id)
    if (Number.isFinite(tid) && tid <= max) {
      return { ...m, status: 'read' }
    }
    return m
  })
}

export function applyMessageStatus(prev, patch) {
  if (!patch) return prev || []
  return (prev || []).map(m => {
    if (patch.id != null && m.id === patch.id) return { ...m, ...patch }
    if (patch.telegram_id != null && m.telegram_id === patch.telegram_id) return { ...m, ...patch }
    return m
  })
}

export function appendMessageDeduped(prev, msg) {
  const key = dedupeKey(msg)
  if (key && (prev || []).some(m => dedupeKey(m) === key)) {
    return applyOutboundLiveMessage(prev, msg)
  }
  return mergeMessageLists([msg], prev || [])
}

export function applyOutboundLiveMessage(prev, msg) {
  const key = dedupeKey(msg)
  let replaced = false
  const next = (prev || []).map(m => {
    if (key && dedupeKey(m) === key) {
      replaced = true
      return { ...m, ...msg }
    }
    if (msg?.id && m.id === msg.id) {
      replaced = true
      return { ...m, ...msg }
    }
    return m
  })
  if (!replaced) next.push(msg)
  return next.sort((a, b) => messageSortKey(a) - messageSortKey(b))
}

export function defaultOutboundStatus(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'sending') return 'sending'
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'read') return 'read'
  if (s === 'delivered') return 'delivered'
  return 'sent'
}
