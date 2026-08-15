import React, { useEffect, useMemo, useState } from 'react'
import { useDialogA11y } from '../hooks/useDialogA11y.js'
import { createPortal } from 'react-dom'
import { API } from '../config.js'
import { Spinner } from '../Loader.jsx'
import { accountLabel } from '../utils/accountUi.js'
import { forwardTmeUrlFromConfig } from '../utils/forwardAccountUtils.js'
import { messagePreviewHtml } from '../utils/messagePreviewHtml.js'

export function InboxMarketingMessageModal({
  open,
  onClose,
  slot,
  postingModeConfig,
}) {
  // Focus in, Tab trapped, focus restored to the trigger. Escape stays
  // below so this dialog's own guard keeps its exact behaviour.
  const dialogRef = useDialogA11y(open, onClose, { closeOnEscape: false })

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [rewriteEnabled, setRewriteEnabled] = useState(false)
  const [forwardPreview, setForwardPreview] = useState(null)
  const [forwardLoading, setForwardLoading] = useState(false)

  const fwd = postingModeConfig?.forwarding || {}
  const campaignOn = postingModeConfig?.campaign_enabled !== false
  const forwardingOn = !!postingModeConfig?.forwarding_enabled
  const forwardSourceType = fwd.source_type === 'telegram_post' ? 'telegram_post' : 'template'
  const forwardTmeUrl = useMemo(() => forwardTmeUrlFromConfig(fwd), [fwd])
  const messageHtml = useMemo(() => messagePreviewHtml(message), [message])

  useEffect(() => {
    if (!open || !slot) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose, slot])

  useEffect(() => {
    if (!open || !slot) return undefined
    let cancelled = false
    setLoading(true)
    setError('')
    setMessage('')
    setForwardPreview(null)
    ;(async () => {
      try {
        const res = await fetch(`${API}/message?slot=${encodeURIComponent(slot)}`, {
          credentials: 'include',
        })
        const data = await res.json()
        if (cancelled) return
        setMessage(data.message || '')
        setRewriteEnabled(!!data.rewrite_enabled)
      } catch (e) {
        if (!cancelled) setError(String(e.message || e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [open, slot])

  useEffect(() => {
    if (!open || !slot || !forwardingOn || forwardSourceType !== 'telegram_post') {
      setForwardPreview(null)
      return undefined
    }
    const peer = String(fwd.source_peer || '').trim()
    const mid = Number(fwd.source_message_id || 0)
    if (!peer || !mid) return undefined
    let cancelled = false
    setForwardLoading(true)
    ;(async () => {
      try {
        const res = await fetch(`${API}/account/${encodeURIComponent(slot)}/forward-message/preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            source_url: forwardTmeUrl,
            source_peer: peer,
            source_message_id: mid,
          }),
        })
        const data = await res.json()
        if (cancelled) return
        if (data.status === 'ok' && data.job?.preview) {
          setForwardPreview(data.job.preview)
        }
      } catch {
        /* optional preview */
      } finally {
        if (!cancelled) setForwardLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [open, slot, forwardingOn, forwardSourceType, fwd.source_peer, fwd.source_message_id, forwardTmeUrl])

  if (!open || !slot) return null

  const modal = (
    <div className="crm-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="crm-modal crm-modal--marketing"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="inbox-marketing-title"
        onClick={e => e.stopPropagation()}
      >
        <header className="inbox-marketing-modal-head">
          <div>
            <h3 id="inbox-marketing-title" className="crm-modal-title">
              Marketing message
            </h3>
            <p className="crm-modal-sub">
              Outbound copy for {accountLabel(slot)}
              {rewriteEnabled ? ' · rewrite on' : ''}
            </p>
          </div>
          <button
            type="button"
            className="inbox-marketing-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </header>

        {loading && (
          <div className="inbox-marketing-modal-loading" aria-busy="true">
            <Spinner size={22} />
            <span>Loading message…</span>
          </div>
        )}

        {error && (
          <p className="inbox-marketing-modal-error" role="alert">{error}</p>
        )}

        {!loading && !error && (
          <div className="inbox-marketing-modal-body">
            {campaignOn && (
              <section className="inbox-marketing-section">
                <h4 className="inbox-marketing-section-title">Campaign template</h4>
                <div
                  className="message-preview-body inbox-marketing-preview"
                  dangerouslySetInnerHTML={{ __html: messageHtml }}
                />
              </section>
            )}

            {forwardingOn && (
              <section className="inbox-marketing-section">
                <h4 className="inbox-marketing-section-title">Forwarding source</h4>
                {forwardSourceType === 'telegram_post' ? (
                  <>
                    {forwardTmeUrl && (
                      <a
                        className="inbox-marketing-link"
                        href={forwardTmeUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Open Telegram post
                      </a>
                    )}
                    {forwardLoading && (
                      <p className="inbox-marketing-hint">Loading post preview…</p>
                    )}
                    {forwardPreview?.text && (
                      <div className="inbox-marketing-forward-preview">
                        <p className="inbox-marketing-hint">Post preview</p>
                        <pre className="inbox-marketing-forward-text">{forwardPreview.text}</pre>
                      </div>
                    )}
                    {!forwardLoading && !forwardPreview?.text && (
                      <p className="inbox-marketing-hint">
                        Native Telegram post — open the link above to view media.
                      </p>
                    )}
                  </>
                ) : (
                  <div
                    className="message-preview-body inbox-marketing-preview"
                    dangerouslySetInnerHTML={{ __html: messageHtml }}
                  />
                )}
              </section>
            )}

            {!campaignOn && !forwardingOn && (
              <p className="inbox-marketing-hint">
                Campaign and forwarding are off for this account. Message text is still shown below if saved.
              </p>
            )}

            {!campaignOn && !forwardingOn && message.trim() && (
              <div
                className="message-preview-body inbox-marketing-preview"
                dangerouslySetInnerHTML={{ __html: messageHtml }}
              />
            )}
          </div>
        )}

        <footer className="inbox-marketing-modal-foot">
          <p className="inbox-marketing-hint">
            Edit on Dashboard → Setup column → Message to send.
          </p>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
            Close
          </button>
        </footer>
      </div>
    </div>
  )

  return createPortal(modal, document.body)
}
