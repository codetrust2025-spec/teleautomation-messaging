/** Per-account forwarding helpers (no cross-account sharing). */

/** Rebuild t.me URL from this account's saved posting_mode forwarding fields only. */
export function forwardTmeUrlFromConfig(fwd) {
  if (!fwd?.source_message_id) return ''
  const label = String(fwd.source_label || '').trim()
  if (label.startsWith('@')) {
    return `https://t.me/${label.slice(1)}`
  }
  if (label.startsWith('c/')) {
    return `https://t.me/${label}`
  }
  const peer = String(fwd.source_peer || '').trim()
  const mid = fwd.source_message_id
  if (peer.startsWith('@')) {
    return `https://t.me/${peer.slice(1)}/${mid}`
  }
  if (peer.startsWith('-100')) {
    return `https://t.me/c/${peer.slice(4)}/${mid}`
  }
  return ''
}
