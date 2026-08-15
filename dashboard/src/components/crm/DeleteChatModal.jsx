import React, { useEffect, useRef, useState } from 'react'
import { Button } from '../ui/Button.jsx'
import { fetchDeleteChatConfig } from '../../utils/deleteChat.js'

export function DeleteChatModal({
  open,
  chatName,
  onCancel,
  onConfirm,
  loading = false,
  error = '',
}) {
  const [password, setPassword] = useState('')
  const [requiresPassword, setRequiresPassword] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    if (!open) {
      setPassword('')
      setRequiresPassword(false)
      return undefined
    }
    let cancelled = false
    fetchDeleteChatConfig().then((cfg) => {
      if (!cancelled) setRequiresPassword(!!cfg.requires_password)
    })
    const t = window.setTimeout(() => inputRef.current?.focus(), 50)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [open])

  if (!open) return null

  return (
    <div
      className="modal-backdrop confirm-backdrop"
      onClick={loading ? undefined : onCancel}
      role="presentation"
    >
      <div
        className="confirm-card confirm-card--danger delete-chat-modal"
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-chat-title"
      >
        <div className="confirm-card-icon confirm-card-icon--danger" aria-hidden>
          🗑
        </div>
        <h2 id="delete-chat-title" className="confirm-card-title">
          Clear chat permanently?
        </h2>
        <p className="confirm-card-message">
          This removes all stored messages and CRM data for{' '}
          <strong>{chatName || 'this lead'}</strong> from the dashboard.
          This cannot be undone. The conversation stays on Telegram.
        </p>
        {requiresPassword && (
          <label className="delete-chat-modal-field">
            <span className="crm-field-label">Delete password</span>
            <input
              ref={inputRef}
              type="password"
              className="input delete-chat-modal-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter delete password"
              autoComplete="off"
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && password.trim() && !loading) {
                  onConfirm(password.trim())
                }
              }}
            />
          </label>
        )}
        {error && (
          <p className="delete-chat-modal-error" role="alert">
            {error}
          </p>
        )}
        <div className="confirm-card-actions">
          <Button variant="ghost" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => onConfirm(requiresPassword ? password.trim() : '')}
            disabled={loading || (requiresPassword && !password.trim())}
          >
            {loading ? 'Clearing…' : 'Clear chat'}
          </Button>
        </div>
      </div>
    </div>
  )
}
