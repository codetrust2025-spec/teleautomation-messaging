import { isBlockedLead } from './crm.js'
import {
  getReplyAlertLevel,
  REPLY_ALERT_BUZZER_MS,
  unansweredElapsedMs,
} from './replyAlert.js'

/** Priority dot: hot (red) | warm (yellow) | active (green) | none */
export function getLeadPriority(conv, now = Date.now()) {
  if (!conv || isBlockedLead(conv)) return 'none'
  const level = getReplyAlertLevel(conv, now)
  if (level === 'aggressive' || level === 'buzzer') return 'hot'
  if (level === 'soft' || conv.crm_status === 'follow_up') return 'warm'
  if (
    conv.crm_status === 'interested'
    || (conv.unread_count || 0) > 0
    || conv.crm_status === 'converted'
  ) {
    return 'active'
  }
  return 'none'
}

export function getLeadScore(conv, now = Date.now()) {
  const p = getLeadPriority(conv, now)
  if (p === 'hot') return 'hot'
  if (p === 'warm') return 'warm'
  if (p === 'active') return 'warm'
  return 'cold'
}

export function leadScoreLabel(score) {
  if (score === 'hot') return 'Hot'
  if (score === 'warm') return 'Warm'
  return 'Cold'
}

export function formatWaitingTime(conv, now = Date.now()) {
  if (!conv || isBlockedLead(conv)) return ''
  const ms = unansweredElapsedMs(conv, now)
  if (ms == null) return ''
  const mins = Math.floor(ms / 60000)
  if (mins < 1) return '<1m'
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

export function formatWaitingLabel(conv, now = Date.now()) {
  const w = formatWaitingTime(conv, now)
  if (!w) return ''
  return `Waiting ${w}`
}

const URGENCY_RANK = { aggressive: 3, buzzer: 2, soft: 1, none: 0 }

export function conversationUrgencyRank(conv, now = Date.now()) {
  if (isBlockedLead(conv)) return -1
  const level = getReplyAlertLevel(conv, now)
  return URGENCY_RANK[level] ?? 0
}

export function sortConversationsByUrgency(conversations, now = Date.now()) {
  return [...conversations].sort((a, b) => {
    const ra = conversationUrgencyRank(a, now)
    const rb = conversationUrgencyRank(b, now)
    if (rb !== ra) return rb - ra
    const ua = Number(a.unread_count || 0)
    const ub = Number(b.unread_count || 0)
    if (ub !== ua) return ub - ua
    return (b.last_message_at || '').localeCompare(a.last_message_at || '')
  })
}

export function getDynamicQuickReplies(status) {
  const st = status || 'new'
  const base = [
    {
      id: 'resume',
      label: 'Resume format',
      text: 'Here is the resume format we use — please share your details in this structure and we will review.',
    },
    {
      id: 'pricing',
      label: 'Share pricing',
      text: 'Thanks for reaching out. Our pricing depends on the package — I can share options shortly. What are you looking for?',
    },
    {
      id: 'schedule',
      label: 'Schedule call',
      action: 'schedule_call',
    },
  ]

  let smart
  if (st === 'interested') {
    smart = {
      id: 'smart',
      label: 'Sharing details…',
      text: 'Great to hear you are interested — sharing full details with you now.',
    }
  } else if (st === 'follow_up') {
    smart = {
      id: 'smart',
      label: 'Just checking in…',
      text: 'Hi — just checking in to see if you had a chance to review my last message.',
    }
  } else if (st === 'converted') {
    smart = {
      id: 'smart',
      label: 'Thanks for joining',
      text: 'Thank you for connecting with us. Let me know if you need anything else.',
    }
  } else {
    smart = {
      id: 'smart',
      label: 'How can I help?',
      text: 'Hi — thanks for reaching out. How can I help you today?',
    }
  }

  return [smart, ...base]
}

export function callChannelLabel(callType) {
  if (callType === 'whatsapp') return 'WhatsApp'
  if (callType === 'phone') return 'Phone'
  return 'Telegram'
}
