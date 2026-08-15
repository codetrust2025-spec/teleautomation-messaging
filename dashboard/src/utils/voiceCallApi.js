import { API } from '../config.js'

export async function startVoiceCall(slot, userId, {
  callMode = 'telegram',
  sendJoinDm = false,
  assignedTo = '',
} = {}) {
  const res = await fetch(`${API}/voice/calls/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      account_id: slot,
      user_id: Number(userId),
      send_join_dm: sendJoinDm,
      assigned_to: assignedTo,
      call_mode: callMode,
    }),
  })
  let data
  try {
    data = await res.json()
  } catch {
    throw new Error(`Could not start call (HTTP ${res.status})`)
  }
  if (data.status !== 'ok') {
    throw new Error(data.message || 'Could not start call')
  }
  return data
}

export async function endVoiceCall(sessionId, {
  status = 'ended',
  outcome = '',
  notes = '',
} = {}) {
  const res = await fetch(`${API}/voice/calls/${encodeURIComponent(sessionId)}/end`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ status, outcome, notes }),
  })
  let data
  try {
    data = await res.json()
  } catch {
    throw new Error(`Could not end call (HTTP ${res.status})`)
  }
  if (data.status !== 'ok') {
    throw new Error(data.message || 'Could not end call')
  }
  return data
}
