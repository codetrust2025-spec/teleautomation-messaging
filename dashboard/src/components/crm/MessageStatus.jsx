import React from 'react'
import { defaultOutboundStatus } from '../../utils/inboxMessageUtils.js'

export function MessageStatus({ direction, status }) {
  if (direction !== 'out') {
    if (status === 'read') {
      return <span className="inbox-msg-status inbox-msg-status--seen" title="Seen">Seen</span>
    }
    return null
  }
  const st = defaultOutboundStatus(status)
  if (st === 'sending') {
    return (
      <span className="inbox-msg-status inbox-msg-status--sending" title="Sending" aria-label="Sending">
        ⏳
      </span>
    )
  }
  if (st === 'failed') {
    return (
      <span className="inbox-msg-status inbox-msg-status--failed" title="Failed to send" aria-label="Failed">
        ✕
      </span>
    )
  }
  if (st === 'read') {
    return (
      <span className="inbox-msg-status inbox-msg-status--read" title="Read by contact">
        ✓✓
      </span>
    )
  }
  if (st === 'delivered') {
    return (
      <span className="inbox-msg-status inbox-msg-status--delivered" title="Delivered">
        ✓✓
      </span>
    )
  }
  return (
    <span className="inbox-msg-status inbox-msg-status--sent" title="Sent">
      ✓
    </span>
  )
}
