import { formatIstDate, istDayKey, parseInstant } from '../utils/istTime.js'

/** Avatar hue from stable string (no external assets). */
export function avatarHue(seed) {
  let h = 0
  const s = String(seed || '?')
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
  return h
}

export function displayInitials(name, fallback = '?') {
  const raw = String(name || '').trim()
  if (!raw) return fallback.slice(0, 2).toUpperCase()
  const parts = raw.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return raw.slice(0, 2).toUpperCase()
}

export function formatDateSeparator(iso) {
  if (!iso) return ''
  const d = parseInstant(iso)
  if (!d) return ''
  const day = istDayKey(d)
  if (day === istDayKey()) return 'Today'
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)
  if (day === istDayKey(yesterday)) return 'Yesterday'
  return formatIstDate(d, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: new Date().getFullYear() !== d.getFullYear() ? 'numeric' : undefined,
  })
}

/** Inbox media URL — WA messages use wa-media cache route. */
export function inboxMediaSrc(apiBase, slot, userId, messageId, channel = 'telegram') {
  const segment = channel === 'whatsapp' ? 'wa-media' : 'media'
  return `${apiBase}/inbox/${encodeURIComponent(slot)}/${segment}/${Number(userId)}/${Number(messageId)}`
}

/** Message channel: whatsapp | telegram */
export function messageChannel(message) {
  const ch = String(message?.channel || '').toLowerCase()
  if (ch === 'whatsapp' || ch === 'telegram') return ch
  return 'telegram'
}

/** Default reply channel from thread history and conv metadata. */
export function pickReplyChannel(messages, conv) {
  const channels = conv?.channels || []
  if (channels.length === 1 && channels[0] === 'whatsapp') return 'whatsapp'
  if (Number(conv?.user_id) < 0) return 'whatsapp'
  const msgs = messages || []
  for (let i = msgs.length - 1; i >= 0; i -= 1) {
    const m = msgs[i]
    if (m?.direction === 'in') return messageChannel(m)
  }
  if (conv?.whatsapp_linked && channels.includes('whatsapp')) return 'whatsapp'
  return 'telegram'
}

/** Short badges for conversation list: ['wa', 'tg'] */
export function conversationChannelBadges(conv) {
  const channels = conv?.channels || []
  const badges = []
  if (channels.includes('whatsapp') || Number(conv?.user_id) < 0) badges.push('wa')
  if (channels.includes('telegram') && Number(conv?.user_id) > 0) badges.push('tg')
  if (badges.length === 0) badges.push('tg')
  return badges
}

export function formatUnreadCount(n) {
  const v = Number(n) || 0
  if (v <= 0) return ''
  if (v >= 1000) return `${(v / 1000).toFixed(1).replace(/\.0$/, '')}K`
  if (v > 99) return '99+'
  return String(v)
}

export function buildMessageTimeline(messages) {
  const items = []
  let lastDateKey = ''
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i]
    const ts = m.timestamp
    let dateKey = ''
    try {
      dateKey = ts ? new Date(ts).toDateString() : ''
    } catch {
      dateKey = ''
    }
    if (dateKey && dateKey !== lastDateKey) {
      items.push({
        kind: 'date',
        id: `date-${dateKey}-${i}`,
        label: formatDateSeparator(ts),
      })
      lastDateKey = dateKey
    }
    items.push({ kind: 'message', id: `msg-${m.id}-${i}`, message: m, index: i })
  }
  return items
}

const VISUAL_MEDIA_TYPES = new Set(['photo', 'document', 'video', 'sticker', 'voice', 'audio'])
const INBOX_MEDIA_TYPES = new Set([...VISUAL_MEDIA_TYPES, 'media'])

export const INBOX_MEDIA_PLACEHOLDERS = new Set([
  '[media]', '[photo]', '[image]', '[video]', '[voice]', '[audio]', '[document]', '[sticker]', '[file]',
])

/** Label for document download/open; uses Telegram filename when stored as message text. */
export function documentFileLabel(message) {
  const t = String(message?.text || '').trim()
  if (!t || INBOX_MEDIA_PLACEHOLDERS.has(t.toLowerCase())) return 'Document'
  if (!/\s/.test(t) && t.length <= 200) return t
  return 'Document'
}

/** True when message text is only a filename (avoid duplicate caption under document card). */
export function isFilenameOnlyCaption(message) {
  const t = String(message?.text || '').trim()
  if (!t || INBOX_MEDIA_PLACEHOLDERS.has(t.toLowerCase())) return false
  return !/\s/.test(t) && /\.[a-z0-9]{1,12}$/i.test(t)
}

export function mediaTypeFromFile(file) {
  if (!file) return 'document'
  const type = String(file.type || '').toLowerCase()
  const name = String(file.name || '').toLowerCase()
  if (type.startsWith('image/')) return 'photo'
  if (type.startsWith('video/')) return 'video'
  if (
    type.startsWith('audio/')
    && (
      type.includes('ogg')
      || type.includes('opus')
      || type.includes('webm')
      || name.endsWith('.ogg')
      || name.endsWith('.opus')
      || name.endsWith('.webm')
    )
  ) {
    return 'voice'
  }
  if (type.startsWith('audio/')) return 'audio'
  return 'document'
}

export function inferMediaKind(message) {
  if (!message) return null
  const textRaw = String(message.text || '').trim()
  const urlOnly = textRaw && !/\s/.test(textRaw) && /(?:https?:\/\/|www\.)/i.test(textRaw)
  if (urlOnly) return null

  const mt = message.media_type
  if (mt && INBOX_MEDIA_TYPES.has(mt)) {
    if (mt === 'media') return message.media ? 'document' : null
    return mt
  }
  const t = String(message.text || '').trim().toLowerCase()
  if (t === '[media]' || t === '[image]') return 'photo'
  if (t === '[photo]' || t.includes('[photo]')) return 'photo'
  if (t.includes('[video]')) return 'video'
  if (t.includes('[voice]') || t.includes('voice note')) return 'voice'
  if (t.includes('[audio]')) return 'audio'
  if (t.includes('[document]') || t.includes('[file]')) return 'document'
  if (t === '[sticker]' || t.includes('[sticker]')) return 'sticker'
  return null
}
