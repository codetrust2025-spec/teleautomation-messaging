const KEY = 'inbox-pinned-messages'

function chatKey(slot, userId) {
  return `${slot}:${userId}`
}

function loadAll() {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveAll(data) {
  try {
    localStorage.setItem(KEY, JSON.stringify(data))
  } catch {
    /* ignore */
  }
}

export function getPinnedIds(slot, userId) {
  const data = loadAll()
  const ids = data[chatKey(slot, userId)]
  return Array.isArray(ids) ? ids.map(Number).filter(Number.isFinite) : []
}

export function isMessagePinned(slot, userId, messageId) {
  return getPinnedIds(slot, userId).includes(Number(messageId))
}

export function toggleMessagePin(slot, userId, messageId) {
  const key = chatKey(slot, userId)
  const data = loadAll()
  const mid = Number(messageId)
  const set = new Set(getPinnedIds(slot, userId))
  if (set.has(mid)) set.delete(mid)
  else set.add(mid)
  data[key] = [...set]
  saveAll(data)
  return set.has(mid)
}
