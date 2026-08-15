import { API } from '../config.js'

export async function fetchDeleteChatConfig() {
  const res = await fetch(`${API}/inbox/delete-config`, { credentials: 'include' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || data.status !== 'ok') {
    return { requires_password: false }
  }
  return { requires_password: !!data.requires_password }
}

export async function deleteInboxConversation(slot, userId, password = '') {
  const res = await fetch(
    `${API}/inbox/${encodeURIComponent(slot)}/conversation/${Number(userId)}`,
    {
      method: 'DELETE',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password || '' }),
    },
  )
  let data = {}
  try {
    data = await res.json()
  } catch {
    data = {}
  }
  if (res.status === 403) {
    throw new Error(data.detail || 'Incorrect delete password')
  }
  if (res.status === 503) {
    throw new Error(data.detail || 'Chat delete is not configured on the server')
  }
  if (data.status !== 'ok') {
    throw new Error(data.message || data.detail || 'Delete failed')
  }
  return data
}
