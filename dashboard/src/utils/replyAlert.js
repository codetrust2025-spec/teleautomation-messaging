/** CRM reply SLA — tiered alerts: 5m soft, 10m buzzer, 20m aggressive. */



import { isBlockedLead } from './crm.js'



export const REPLY_ALERT_SOFT_MS = 5 * 60 * 1000

export const REPLY_ALERT_BUZZER_MS = 10 * 60 * 1000

export const REPLY_ALERT_AGGRESSIVE_MS = 20 * 60 * 1000

/** @deprecated use REPLY_ALERT_BUZZER_MS */

export const REPLY_SLA_MS = REPLY_ALERT_BUZZER_MS



export const REPLY_CHECK_INTERVAL_MS = 30 * 1000

export const BUZZER_BEEP_INTERVAL_MS = 2500

export const AGGRESSIVE_BEEP_INTERVAL_MS = 1200



export const ALERT_LEVEL_ORDER = { soft: 1, buzzer: 2, aggressive: 3 }



const STORAGE_KEY = 'tf_crm_buzzer_alerts_enabled'



export function isBuzzerAlertsEnabled() {

  try {

    return localStorage.getItem(STORAGE_KEY) !== '0'

  } catch {

    return true

  }

}



export function setBuzzerAlertsEnabled(on) {

  try {

    localStorage.setItem(STORAGE_KEY, on ? '1' : '0')

  } catch {

    /* ignore */

  }

  window.dispatchEvent(new CustomEvent('crm-buzzer-toggle'))

}



function parseIso(iso) {

  if (!iso) return null

  const t = Date.parse(String(iso))

  return Number.isFinite(t) ? t : null

}



/** Latest agent action: outbound reply or explicit "handled". */

export function effectiveLastReplyTime(conv) {

  const reply = parseIso(conv.last_reply_time || conv.crm_last_reply_at)

  const handled = parseIso(conv.reply_handled_at || conv.crm_reply_handled_at)

  if (reply == null && handled == null) return null

  if (reply == null) return handled

  if (handled == null) return reply

  return Math.max(reply, handled)

}



export function unansweredElapsedMs(conv, now = Date.now()) {

  const userAt = parseIso(conv.last_user_message_at || conv.crm_last_user_message_at)

  if (userAt == null) return null

  const effReply = effectiveLastReplyTime(conv)

  if (effReply != null && effReply >= userAt) return null

  return now - userAt

}



/**

 * @returns {null | 'soft' | 'buzzer' | 'aggressive'}

 */

export function getReplyAlertLevel(conv, now = Date.now()) {

  if (!conv || isBlockedLead(conv)) return null



  const elapsed = unansweredElapsedMs(conv, now)

  if (elapsed == null) return null

  if (elapsed >= REPLY_ALERT_AGGRESSIVE_MS) return 'aggressive'

  if (elapsed >= REPLY_ALERT_BUZZER_MS) return 'buzzer'

  if (elapsed >= REPLY_ALERT_SOFT_MS) return 'soft'

  return null

}



/** @deprecated use getReplyAlertLevel */

export function isConversationReplyDelayed(conv, now = Date.now()) {

  const level = getReplyAlertLevel(conv, now)

  return level === 'buzzer' || level === 'aggressive'

}



export function replyAlertLabel(level) {

  if (level === 'aggressive') return 'URGENT'

  if (level === 'buzzer') return 'Delayed'

  if (level === 'soft') return '5m+'

  return ''

}



export function conversationAlertKey(conv) {

  return `${conv.account_id || ''}:${conv.user_id}`

}



/** All conversations with level >= soft. */

export function listAlertConversations(inboxState, now = Date.now()) {

  const out = []

  for (const block of Object.values(inboxState?.slots || {})) {

    const slot = block.slot

    for (const c of block.conversations || []) {

      const level = getReplyAlertLevel(c, now)

      if (level) {

        out.push({

          slot: c.account_id || slot,

          user_id: c.user_id,

          conv: c,

          level,

        })

      }

    }

  }

  return out

}



export function getMaxReplyAlertLevel(inboxState, now = Date.now()) {

  let max = null

  for (const item of listAlertConversations(inboxState, now)) {

    if (!max || ALERT_LEVEL_ORDER[item.level] > ALERT_LEVEL_ORDER[max]) {

      max = item.level

    }

  }

  return max

}



export function countAlertConversationsByLevel(inboxState, now = Date.now()) {

  const counts = { soft: 0, buzzer: 0, aggressive: 0, total: 0 }

  for (const item of listAlertConversations(inboxState, now)) {

    counts[item.level] += 1

    counts.total += 1

  }

  return counts

}



/** @deprecated */

export function listDelayedConversations(inboxState, now = Date.now()) {

  return listAlertConversations(inboxState, now).filter(

    i => i.level === 'buzzer' || i.level === 'aggressive',

  )

}



export function countDelayedConversations(inboxState, now = Date.now()) {

  return listDelayedConversations(inboxState, now).length

}



export function formatAlertBanner(counts) {

  if (!counts?.total) return ''

  const waiting10 = (counts.buzzer ?? 0) + (counts.aggressive ?? 0)

  if (waiting10 > 0) {

    return formatUrgentTopBanner(counts)

  }

  return `🔔 ${counts.total} need reply`

}



export function formatUrgentTopBanner(counts) {

  const waiting10 = (counts?.buzzer ?? 0) + (counts?.aggressive ?? 0)

  if (waiting10 <= 0) return ''

  return `⚠ ${waiting10} lead${waiting10 === 1 ? '' : 's'} waiting >10 mins`

}
