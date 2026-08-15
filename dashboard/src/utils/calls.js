import { API } from '../config.js'
import { leadKey } from './crm.js'
import { formatIstDateTime, formatIstTime, istDayKey } from './istTime.js'

export const LIVE_CALL_MESSAGE = 'Can we connect on a quick call now?'

export const CALL_TYPES = [
  { id: 'whatsapp', label: 'WhatsApp' },
  { id: 'phone', label: 'Phone' },
  { id: 'telegram', label: 'Telegram call' },
]

export function callTypeLabel(type) {
  return CALL_TYPES.find(t => t.id === type)?.label || type || 'Call'
}

export function getScheduledCall(crmState, slot, userId) {
  const key = leadKey(slot, userId)
  return crmState?.scheduled_calls?.[key] || null
}

export function formatCallScheduleTime(iso) {
  if (!iso) return ''
  const d = parseInstant(iso)
  if (!d) return String(iso)
  const day = istDayKey(d)
  const time = formatIstTime(d, { hour: 'numeric', minute: '2-digit', second: undefined, hour12: true })
  if (day === istDayKey()) return `${time} today (IST)`
  const tomorrow = new Date()
  tomorrow.setDate(tomorrow.getDate() + 1)
  if (day === istDayKey(tomorrow)) return `${time} tomorrow (IST)`
  return `${formatIstDateTime(d)} IST`
}

/** Prefer Telegram, then WhatsApp, then phone — for one-tap outgoing call UI. */
export function pickDefaultLiveCallOption(contact) {
  const options = buildLiveCallOptions(contact || {})
  const order = ['telegram', 'whatsapp', 'phone']
  for (const id of order) {
    const opt = options.find(o => o.id === id && o.can_open)
    if (opt) return opt
  }
  return options.find(o => o.can_open) || null
}

export function buildLiveCallOptions(contact) {
  const username = String(contact?.username || '').replace(/^@/, '')
  const phone = String(contact?.phone || '').replace(/\D/g, '')
  const uid = contact?.user_id

  return [
    {
      id: 'whatsapp',
      label: 'WhatsApp Call',
      hint: phone ? 'Opens WhatsApp — tap call there' : 'No phone number on file',
      can_open: Boolean(phone),
      url: phone ? `https://wa.me/${phone}` : null,
    },
    {
      id: 'phone',
      label: 'Phone Call',
      hint: phone ? 'Opens your phone dialer' : 'No phone number on file',
      can_open: Boolean(phone),
      url: phone ? `tel:+${phone}` : null,
    },
    {
      id: 'telegram',
      label: 'Telegram (open chat)',
      hint: (username || uid) ? 'Open chat — start voice call in Telegram' : 'No Telegram username',
      can_open: Boolean(username || uid),
      url: username ? `https://t.me/${username}` : (uid ? `tg://user?id=${uid}` : null),
    },
  ]
}

export function buildLiveCallInitiatedMessage(attempt) {
  const type = callTypeLabel(attempt?.call_type)
  return `📞 Call initiated (${type})`
}

export function buildCallLink(call) {
  if (!call) return { url: null, label: 'No call scheduled', can_open: false }
  const ct = call.call_type || 'telegram'
  const username = String(call.username || '').replace(/^@/, '')
  const phone = String(call.phone || '').replace(/\D/g, '')
  const uid = call.user_id

  if (ct === 'whatsapp') {
    if (phone) return { url: `https://wa.me/${phone}`, label: 'Open WhatsApp', can_open: true }
    if (username) {
      return { url: `https://t.me/${username}`, label: 'Open Telegram (no WA number)', can_open: true }
    }
    return { url: null, label: 'No phone on file', can_open: false }
  }
  if (ct === 'phone') {
    if (phone) return { url: `tel:+${phone}`, label: 'Call number', can_open: true }
    return { url: null, label: 'No phone on file', can_open: false }
  }
  if (username) return { url: `https://t.me/${username}`, label: 'Open Telegram', can_open: true }
  if (uid) return { url: `tg://user?id=${uid}`, label: 'Open Telegram', can_open: true }
  return { url: null, label: 'No Telegram username', can_open: false }
}

export function toLocalISO(dateStr, timeStr) {
  if (!dateStr || !timeStr) return null
  const local = new Date(`${dateStr}T${timeStr}`)
  if (Number.isNaN(local.getTime())) return null
  return local.toISOString()
}

export function buildCallSystemMessage(call) {
  const when = formatCallScheduleTime(call?.scheduled_time)
  const type = callTypeLabel(call?.call_type)
  return `📞 Call scheduled for ${when} (${type})${call?.notes ? ` — ${call.notes}` : ''}`
}

export async function scheduleCall(slot, userId, body) {
  const payload = {
    account_id: slot,
    user_id: Number(userId),
    scheduled_time: body.scheduled_time,
    call_type: body.call_type || 'telegram',
    notes: body.notes || '',
  }
  const res = await fetch(`${API}/crm/schedule-call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  let data
  try {
    data = await res.json()
  } catch {
    throw new Error(`Could not schedule call (HTTP ${res.status})`)
  }
  if (data.status !== 'ok') throw new Error(data.message || 'Could not schedule call')
  return data
}

export async function initiateLiveCall(slot, userId, callType) {
  const res = await fetch(`${API}/crm/call-now`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      account_id: slot,
      user_id: Number(userId),
      call_type: callType,
      send_message: true,
    }),
  })
  let data
  try {
    data = await res.json()
  } catch {
    throw new Error(`Call failed (HTTP ${res.status})`)
  }
  if (data.status !== 'ok') throw new Error(data.message || 'Call failed')
  return data
}

export async function completeCall(slot, userId, outcomeStatus) {
  const res = await fetch(
    `${API}/crm/leads/${encodeURIComponent(slot)}/${userId}/calls/complete`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outcome_status: outcomeStatus }),
    },
  )
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Could not save call outcome')
  return data
}
