const PREFIX = 'inbox-draft:'

export function draftKey(slot, userId) {
  return `${PREFIX}${slot}:${Number(userId)}`
}

export function loadDraft(slot, userId) {
  try {
    return localStorage.getItem(draftKey(slot, userId)) || ''
  } catch {
    return ''
  }
}

export function saveDraft(slot, userId, text) {
  try {
    const key = draftKey(slot, userId)
    const v = String(text || '')
    if (!v.trim()) {
      localStorage.removeItem(key)
    } else {
      localStorage.setItem(key, v)
    }
  } catch {
    /* private mode / quota */
  }
}

export function clearDraft(slot, userId) {
  try {
    localStorage.removeItem(draftKey(slot, userId))
  } catch {
    /* ignore */
  }
}
