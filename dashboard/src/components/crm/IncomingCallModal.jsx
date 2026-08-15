import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { accountLabel } from '../../utils/accountUi.js'

function telegramOpenUrl(call) {
  const username = String(call?.username || '').replace(/^@/, '')
  const uid = call?.user_id
  if (username) return `https://t.me/${username}`
  if (uid) return `tg://user?id=${uid}`
  return null
}

export function IncomingCallModal({ call, onDismiss }) {
  useEffect(() => {
    const onKey = e => {
      if (e.key === 'Escape') onDismiss()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onDismiss])

  if (!call) return null

  const url = telegramOpenUrl(call)
  const video = Boolean(call.video)

  const modal = (
    <div className="crm-modal-backdrop crm-incoming-call-backdrop" role="presentation">
      <div
        className="crm-modal crm-incoming-call-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="incoming-call-title"
        onClick={e => e.stopPropagation()}
      >
        <div className="crm-incoming-call-pulse" aria-hidden>📞</div>
        <h3 id="incoming-call-title" className="crm-modal-title">
          Incoming {video ? 'video' : 'voice'} call
        </h3>
        <p className="crm-incoming-call-name">{call.name || call.username || call.user_id}</p>
        <p className="crm-modal-sub">
          via {accountLabel(call.slot)}
          {call.username ? ` · @${String(call.username).replace(/^@/, '')}` : ''}
        </p>
        <p className="crm-incoming-call-hint">
          Answer in the <strong>Telegram</strong> app (desktop or phone). This dashboard alerts you
          when someone calls your linked account — voice is handled by Telegram, not in the browser.
        </p>
        <div className="crm-incoming-call-actions">
          {url && (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => {
                window.open(url, '_blank', 'noopener,noreferrer')
                onDismiss()
              }}
            >
              Open Telegram to answer
            </button>
          )}
          <button type="button" className="btn btn--ghost" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )

  return createPortal(modal, document.body)
}
