const IMPORTANT_LINE = /(?:\+?\d[\d\s\-]{8,}\d|whatsapp|wa\.me|t\.me\/|http|@|telegram)/i

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** HTML preview for multi-line outbound / campaign messages. */
export function messagePreviewHtml(text) {
  const raw = String(text || '')
  if (!raw.trim()) return '<em class="muted">No message saved for this account.</em>'
  return raw.split('\n').map((line) => {
    const body = esc(line) || '&nbsp;'
    const cls = IMPORTANT_LINE.test(line)
      ? 'message-preview-line message-preview-line--important'
      : 'message-preview-line'
    return `<div class="${cls}">${body}</div>`
  }).join('')
}
