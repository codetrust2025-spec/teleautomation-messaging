import { API } from '../config.js'

/** Trigger browser download for one inbox thread export. */
export async function downloadInboxChatExport(slot, userId, format = 'txt') {
  const uid = Number(userId)
  if (!slot || !Number.isFinite(uid)) {
    throw new Error('Select a conversation first')
  }
  const fmt = String(format || 'txt').toLowerCase()
  const url = `${API}/inbox/${encodeURIComponent(slot)}/messages/${uid}/export?format=${encodeURIComponent(fmt)}`
  const res = await fetch(url, { credentials: 'include' })
  if (!res.ok) {
    let detail = `Export failed (${res.status})`
    try {
      const data = await res.json()
      if (data?.message || data?.detail) detail = data.message || data.detail
    } catch {
      try {
        detail = await res.text()
      } catch {
        /* ignore */
      }
    }
    throw new Error(detail)
  }
  const blob = await res.blob()
  let filename = `chat_${slot}_${uid}.${fmt === 'json' ? 'json' : fmt === 'csv' ? 'csv' : 'txt'}`
  const dispo = res.headers.get('Content-Disposition') || ''
  const match = /filename="?([^";\n]+)"?/i.exec(dispo)
  if (match?.[1]) filename = match[1].trim()
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 2000)
}
