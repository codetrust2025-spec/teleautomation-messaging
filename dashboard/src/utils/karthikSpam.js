import { API } from '../config.js'

export async function karthikScanAndBlockSpam({ slot = null } = {}) {
  const body = slot ? { account_id: slot } : {}
  const res = await fetch(`${API}/crm/karthik/block-spam-chats`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Spam scan failed')
  return data
}

export async function karthikBlockChat(slot, userId) {
  const res = await fetch(
    `${API}/inbox/${encodeURIComponent(slot)}/karthik/block-spam/${userId}`,
    { method: 'POST' },
  )
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Block failed')
  return data
}

export async function karthikSpamCheck(slot, userId) {
  const res = await fetch(
    `${API}/inbox/${encodeURIComponent(slot)}/karthik/spam-check/${userId}`,
    { cache: 'no-store' },
  )
  const data = await res.json()
  if (data.status !== 'ok') throw new Error(data.message || 'Spam check failed')
  return data
}
