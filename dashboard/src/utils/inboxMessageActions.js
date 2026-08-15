import { API } from '../config.js'

async function parseApiJson(res) {
  const raw = await res.text()
  if (!raw.trim()) {
    return { status: 'error', message: res.ok ? 'Empty response' : `HTTP ${res.status}` }
  }
  try {
    return JSON.parse(raw)
  } catch {
    const hint = raw.trimStart().startsWith('<')
      ? 'Server returned HTML (session expired or route not found). Hard-refresh and log in again.'
      : 'Invalid server response'
    return { status: 'error', message: `${hint} (HTTP ${res.status})` }
  }
}

export async function patchInboxMessage(slot, userId, messageId, text) {
  const res = await fetch(
    `${API}/inbox/${encodeURIComponent(slot)}/messages/${userId}/${messageId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ text }),
    },
  )
  return parseApiJson(res)
}

export async function deleteInboxMessage(slot, userId, messageId) {
  const res = await fetch(
    `${API}/inbox/${encodeURIComponent(slot)}/messages/${userId}/${messageId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    },
  )
  return parseApiJson(res)
}
