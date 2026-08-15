import React, { useState, useEffect, useMemo } from 'react'
import { API } from '../config.js'
import { ButtonContent, OverlayLoader } from '../Loader.jsx'
import { accountLabel } from '../utils/accountUi.js'

export function MessageEditor({ customMessage, slot, onSaved, rewriteEnabled, cyclePreview }) {
  const [text, setText] = useState(customMessage || '')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [showPreview, setShowPreview] = useState(false)

  useEffect(() => { setText(customMessage || '') }, [customMessage, slot])

  const charCount = text.length
  const lineCount = text.split('\n').length
  const textareaRows = Math.min(24, Math.max(12, lineCount + 1))

  const IMPORTANT_LINE = /(?:\+?\d[\d\s\-]{8,}\d|whatsapp|wa\.me|t\.me\/|http|@|telegram)/i

  const previewHtml = useMemo(() => {
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return text.split('\n').map(line => {
      const body = esc(line) || '&nbsp;'
      const cls = IMPORTANT_LINE.test(line) ? 'message-preview-line message-preview-line--important' : 'message-preview-line'
      return `<div class="${cls}">${body}</div>`
    }).join('')
  }, [text])

  async function save() {
    setSaving(true)
    try {
      await fetch(`${API}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, slot }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="panel panel--message">
      <button type="button" className="panel-toggle panel-toggle--message" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <div className="panel-toggle-leading">
          <span className="panel-toggle-title">Message to send</span>
          {slot && (
            <span className="panel-toggle-slot" title="Saved only for this account">
              {accountLabel(slot)}
            </span>
          )}
          {!open && text.trim() && (
            <span className="panel-toggle-snippet">{text.split('\n')[0].slice(0, 72)}{text.length > 72 ? '…' : ''}</span>
          )}
        </div>
        <span className="panel-toggle-meta">{charCount} chars · {lineCount} lines</span>
        <span className="panel-toggle-chevron" aria-hidden>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="panel-body panel-body--message">
          {saving && <OverlayLoader label="Saving message…" />}
          <div className="message-editor-main">
            <textarea
              className="input input--textarea input--message"
              value={text}
              onChange={e => setText(e.target.value)}
              rows={textareaRows}
              spellCheck={false}
              placeholder={`Template for ${slot ? accountLabel(slot) : 'this account'} — other accounts keep their own message…`}
              aria-label="Message to send"
            />
          </div>
          <div className="message-meta">
            <span className={`char-counter${charCount > 4000 ? ' char-counter--warn' : ''}`}>
              {charCount} characters · {lineCount} lines
            </span>
            <div className="message-meta-actions">
              {rewriteEnabled && (
                <span className="message-rewrite-badge">Rewrite ON</span>
              )}
              <button
                type="button"
                className="btn btn--ghost btn--sm message-preview-toggle"
                onClick={() => setShowPreview(p => !p)}
              >
                {showPreview ? 'Hide preview' : 'Show preview'}
              </button>
            </div>
          </div>
          {rewriteEnabled && (
            <p className="field-hint message-field-hint">
              Per-cycle rewrite varies the opener each cycle. Phone / WhatsApp lines stay fixed.
              {cyclePreview ? (
                <span className="cycle-preview-line">Active opener: {cyclePreview}</span>
              ) : null}
            </p>
          )}
          {showPreview && (
            <div className="message-preview">
              <div className="message-preview-label">Formatted preview</div>
              <div
                className="message-preview-body"
                dangerouslySetInnerHTML={{ __html: previewHtml || '<em class="muted">Empty message</em>' }}
              />
            </div>
          )}
          <div className="btn-row message-btn-row">
            <button type="button" className="btn btn--primary" onClick={save} disabled={saving}>
              <ButtonContent loading={saving} loadingLabel="Saving…">
                {saved ? '✓ Saved' : 'Save message'}
              </ButtonContent>
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setOpen(false)} disabled={saving}>
              Collapse
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
