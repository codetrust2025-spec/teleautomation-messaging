import React, { memo } from 'react'
import { formatInboxTime } from '../utils/inboxMessageUtils.js'

function previewText(m) {
  const t = (m?.text || '').trim()
  if (t) return t.length > 120 ? `${t.slice(0, 120)}…` : t
  if (m?.media || m?.media_type) return 'Media message'
  return 'Message'
}

function ReplyQuoteBarInner({ message, onClear }) {
  if (!message) return null
  const out = message.direction === 'out'
  const label = out
    ? (message.sender_name || 'You')
    : 'Lead'
  return (
    <div className="tg-reply-quote" role="region" aria-label="Replying to message">
      <div className="tg-reply-quote-bar" aria-hidden />
      <div className="tg-reply-quote-body">
        <span className="tg-reply-quote-title">{label}</span>
        <span className="tg-reply-quote-text">{previewText(message)}</span>
        {message.timestamp && (
          <span className="tg-reply-quote-time">{formatInboxTime(message.timestamp)}</span>
        )}
      </div>
      <button
        type="button"
        className="tg-reply-quote-close"
        onClick={onClear}
        aria-label="Cancel reply"
        title="Cancel reply"
      >
        ×
      </button>
    </div>
  )
}

export const ReplyQuoteBar = memo(ReplyQuoteBarInner)
