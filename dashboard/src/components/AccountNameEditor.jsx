import React, { useEffect, useRef, useState } from 'react'
import { API } from '../config.js'
import { telegramDisplayName, telegramLegalName } from '../utils/accountUi.js'

/**
 * Inline rename for account profile label (stored as display_name per slot).
 */
export function AccountNameEditor({
  slot,
  info,
  onRenamed,
  compact = false,
  selected = true,
  startEditing = false,
  onEditingChange,
}) {
  const shown = telegramDisplayName(info) || slot
  const telegramName = telegramLegalName(info)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  function setEditMode(next) {
    setEditing(next)
    onEditingChange?.(next)
  }

  useEffect(() => {
    if (!startEditing || !info) return
    setValue(String(info?.display_name || telegramName || shown || '').trim())
    setError('')
    setEditMode(true)
  }, [startEditing, info, slot, telegramName, shown])

  // Mini cards stay mounted when you pick another account — exit rename so Save isn’t left open.
  useEffect(() => {
    if (!compact || selected) return
    if (editing) {
      setEditMode(false)
      setError('')
    }
  }, [compact, selected, editing])

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  function openEdit(e) {
    e?.stopPropagation?.()
    e?.preventDefault?.()
    setValue(String(info?.display_name || telegramName || shown || '').trim())
    setError('')
    setEditMode(true)
  }

  function cancelEdit(e) {
    e?.stopPropagation?.()
    setEditMode(false)
    setError('')
  }

  async function saveEdit(e) {
    e?.stopPropagation?.()
    const trimmed = value.trim()
    if (!trimmed) {
      setError('Name cannot be empty')
      return
    }
    if (trimmed.length > 48) {
      setError('Max 48 characters')
      return
    }
    setSaving(true)
    setError('')
    try {
      const res = await fetch(`${API}/account/${slot}/display-name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: trimmed }),
      })
      const data = await res.json()
      if (!res.ok || !data.success) {
        setError(data.error || data.message || 'Could not save name')
        return
      }
      setEditMode(false)
      onRenamed?.(slot, data.account_info)
    } catch (err) {
      setError(err.message || 'Could not save name')
    } finally {
      setSaving(false)
    }
  }

  if (!info) {
    return compact
      ? <span className="account-mini-name">{shown}</span>
      : <h3 className="acct-v3-name">{shown}</h3>
  }

  if (editing) {
    return (
      <div
        className={`account-name-editor account-name-editor--edit${compact ? ' account-name-editor--compact' : ''}`}
        onClick={e => e.stopPropagation()}
        onKeyDown={e => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="input account-name-editor-input"
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') saveEdit(e)
            if (e.key === 'Escape') cancelEdit(e)
          }}
          placeholder="Profile name"
          disabled={saving}
          maxLength={48}
          aria-label="Profile display name"
        />
        <div className="account-name-editor-actions">
          <button type="button" className="btn btn--primary btn--sm" onClick={saveEdit} disabled={saving}>
            {saving ? '…' : 'Save'}
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={cancelEdit} disabled={saving}>
            Cancel
          </button>
        </div>
        {error && <p className="field-error account-name-editor-error">{error}</p>}
        {telegramName && value.trim() !== telegramName && (
          <p className="account-name-editor-hint">Telegram: {telegramName}</p>
        )}
      </div>
    )
  }

  return (
    <div className={`account-name-editor${compact ? ' account-name-editor--compact' : ''}`}>
      {compact ? (
        <span className="account-mini-name" title={shown}>
          {shown}
        </span>
      ) : (
        <button
          type="button"
          className="acct-v3-name acct-v3-name--editable"
          title={`${shown} — click to rename`}
          onClick={openEdit}
        >
          {shown}
        </button>
      )}
      {(!compact || selected) && (
        <button
          type="button"
          className={`account-name-edit-btn${compact ? ' account-name-edit-btn--compact' : ''}`}
          onClick={openEdit}
          title="Rename profile"
          aria-label={`Rename ${shown}`}
        >
          {compact ? 'Edit' : 'Rename'}
        </button>
      )}
    </div>
  )
}
