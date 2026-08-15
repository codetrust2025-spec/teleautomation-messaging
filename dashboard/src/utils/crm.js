import { API } from '../config.js'

export const CRM_STATUS_SPAM = 'spam'

export const CRM_STATUSES = [
  { id: 'new', label: 'New' },
  { id: 'interested', label: 'Interested' },
  { id: 'follow_up', label: 'Follow-up' },
  { id: 'not_interested', label: 'Not Interested' },
  { id: 'converted', label: 'Converted' },
  { id: 'spam', label: 'Spam / Timepass' },
]

export const CRM_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'interested', label: 'Interested' },
  { id: 'follow_up', label: 'Follow-up' },
  { id: 'converted', label: 'Converted' },
  { id: 'spam', label: 'Spam / Blocked' },
  { id: 'unread', label: 'Unread' },
]

export function isSpamStatus(status) {
  return status === CRM_STATUS_SPAM
}

export function isBlockedLead(convOrLead) {
  if (!convOrLead) return false
  return Boolean(convOrLead.crm_blocked) || convOrLead.status === CRM_STATUS_SPAM || isSpamStatus(convOrLead.crm_status)
}

/** True if slot:user_id is on the CRM block list or lead status is spam. */
export function isBlockedInCrmState(crmState, slot, userId) {
  if (!crmState || !slot || userId == null) return false
  const key = leadKey(slot, userId)
  if (crmState.block_list?.[key]) return true
  const lead = crmState.leads?.[key]
  return isBlockedLead(lead)
}

export function applyCrmBlockFlags(conv, crmState) {
  if (!conv || !crmState) return conv
  const slot = conv.account_id || conv.slot
  const uid = conv.user_id
  if (!isBlockedInCrmState(crmState, slot, uid)) return conv
  return {
    ...conv,
    crm_blocked: true,
    crm_status: CRM_STATUS_SPAM,
  }
}

export async function markReplyHandled(slot, userId) {
  const res = await fetch(`${API}/crm/leads/${encodeURIComponent(slot)}/${userId}/mark-handled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Mark handled failed')
  return data
}

export async function unblockLead(slot, userId) {
  const res = await fetch(`${API}/crm/unblock`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_id: slot, user_id: Number(userId) }),
  })
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Unblock failed')
  return data
}

export const QUICK_REPLIES = [
  {
    id: 'resume',
    label: 'Send Resume Format',
    text: 'Here is the resume format we use — please share your details in this structure and we will review.',
  },
  {
    id: 'pricing',
    label: 'Share Pricing',
    text: 'Thanks for reaching out. Our pricing depends on the package — I can share options shortly. What are you looking for?',
  },
  {
    id: 'call',
    label: 'Schedule Call',
    action: 'schedule_call',
  },
]

export function statusLabel(status) {
  return CRM_STATUSES.find(s => s.id === status)?.label || 'New'
}

export function leadKey(slot, userId) {
  return `${slot}:${Number(userId)}`
}

export async function fetchCrmState() {
  const res = await fetch(`${API}/crm/state?t=${Date.now()}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`CRM HTTP ${res.status}`)
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'CRM load failed')
  return {
    leads: data.leads || {},
    stats: data.stats || {},
    due_reminders: data.due_reminders || [],
    scheduled_calls: data.scheduled_calls || {},
    call_reminders: data.call_reminders || [],
    past_due_calls: data.past_due_calls || [],
    block_list: data.block_list || {},
    blocked_count: data.blocked_count ?? 0,
  }
}

export async function patchLead(slot, userId, body) {
  const res = await fetch(`${API}/crm/leads/${encodeURIComponent(slot)}/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Update failed')
  return data
}

export async function scheduleFollowUp(slot, userId, hours) {
  const res = await fetch(
    `${API}/crm/leads/${encodeURIComponent(slot)}/${userId}/follow-up`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours }),
    },
  )
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Follow-up failed')
  return data
}

export function mergeCrmIntoConversation(conv, leadsMap, blockList) {
  const key = leadKey(conv.account_id || conv.slot, conv.user_id)
  const lead = leadsMap?.[key]
  const blocked = Boolean(blockList?.[key]) || isBlockedLead(lead)
  const base = lead
    ? {
        ...conv,
        crm_status: lead.status || conv.crm_status || 'new',
        crm_notes: lead.notes ?? conv.crm_notes ?? '',
        crm_reminder_timestamp: lead.reminder_timestamp,
        crm_reminder_due: lead.reminder_due,
      }
    : conv
  if (!blocked) return base
  return { ...base, crm_blocked: true, crm_status: CRM_STATUS_SPAM }
}
