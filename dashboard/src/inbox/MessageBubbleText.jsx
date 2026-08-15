import React, { Fragment, memo } from 'react'

/** No /g flag — global regex breaks String.split() match positions. */
const URL_SEGMENT = /((?:https?:\/\/|www\.)[^\s<>'"[\]{}|\\^`]+)/i
const URL_TEST = /(?:https?:\/\/|www\.)/i
const URL_TOKEN = /^(?:https?:\/\/|www\.)/i

export function isUrlOnlyMessageText(text) {
  const raw = String(text || '').trim()
  if (!raw || /\s/.test(raw)) return false
  return URL_TEST.test(raw)
}

export function primaryUrlFromText(text) {
  const raw = String(text || '').trim()
  if (!isUrlOnlyMessageText(raw)) return null
  const m = raw.match(/(?:https?:\/\/|www\.)[^\s<>'"[\]{}|\\^`]+/i)
  if (!m) return null
  let core = m[0].replace(/[),.;!?]+$/g, '')
  if (/^www\./i.test(core)) core = `https://${core}`
  return core
}

function normalizeHref(url) {
  const trimmed = url.trim()
  if (/^www\./i.test(trimmed)) return `https://${trimmed}`
  return trimmed
}

/** Strip trailing punctuation that often follows a URL in prose. */
function hrefFromToken(token) {
  const m = token.match(/^(?:https?:\/\/|www\.)[^\s<>'"[\]{}|\\^`]+/i)
  if (!m) return normalizeHref(token)
  let core = m[0]
  core = core.replace(/[),.;!?]+$/g, '')
  return normalizeHref(core)
}

function linkifyText(text) {
  const raw = String(text || '')
  if (!raw) return null

  if (isUrlOnlyMessageText(raw)) {
    const href = primaryUrlFromText(raw)
    if (!href) return raw
    return (
      <a
        className="inbox-message-link inbox-message-link--solo"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
      >
        {raw}
      </a>
    )
  }

  const parts = raw.split(URL_SEGMENT).filter((p) => p !== '')
  if (parts.length <= 1 && !URL_TOKEN.test(raw)) {
    return raw
  }
  return parts.map((part, i) => {
    if (URL_TOKEN.test(part)) {
      const href = hrefFromToken(part)
      return (
        <a
          key={`link-${i}`}
          className="inbox-message-link"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
        >
          {part}
        </a>
      )
    }
    return <Fragment key={`t-${i}`}>{part}</Fragment>
  })
}
function MessageBubbleTextInner({ text, className = '' }) {
  const content = linkifyText(text)
  if (content == null) return null
  const cls = ['inbox-bubble-text', 'tg-bubble-text', className].filter(Boolean).join(' ')
  if (typeof content === 'string') {
    return <div className={cls}>{content}</div>
  }
  return <div className={cls}>{content}</div>
}

export const MessageBubbleText = memo(MessageBubbleTextInner)
