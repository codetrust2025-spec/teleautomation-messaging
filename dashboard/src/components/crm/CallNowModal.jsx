import React, { useEffect, useMemo } from 'react'
import { useDialogA11y } from '../../hooks/useDialogA11y.js'
import { createPortal } from 'react-dom'
import { buildLiveCallOptions } from '../../utils/calls.js'

export function CallNowModal({
  open,
  contact,
  leadName,
  onSelect,
  onClose,
  loading,
}) {
  // Focus in, Tab trapped, focus restored to the trigger. Escape stays
  // below so this dialog's own guard keeps its exact behaviour.
  const dialogRef = useDialogA11y(open, onClose, { closeOnEscape: false })

  const options = useMemo(
    () => buildLiveCallOptions(contact || {}),
    [contact],
  )

  useEffect(() => {
    if (!open) return undefined
    const onKey = e => {
      if (e.key === 'Escape' && !loading) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, loading, onClose])

  if (!open) return null

  const modal = (
    <div className="crm-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="crm-modal crm-modal--compact"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="call-now-title"
        onClick={e => e.stopPropagation()}
      >
        <h3 id="call-now-title" className="crm-modal-title">
          📞 Call now{leadName ? ` · ${leadName}` : ''}
        </h3>
        <p className="crm-modal-sub">
          Pick a channel. We send a quick message and open the app — start the voice call inside
          Telegram (or WhatsApp / phone). Calls are not placed from the browser.
        </p>

        <div className="crm-call-now-options">
          {options.map(opt => (
            <button
              key={opt.id}
              type="button"
              className={`btn btn--block crm-call-now-option${opt.can_open ? '' : ' crm-call-now-option--disabled'}`}
              disabled={!opt.can_open || loading}
              title={opt.hint}
              onClick={() => opt.can_open && onSelect(opt)}
            >
              <span className="crm-call-now-option-label">{opt.label}</span>
              <span className="crm-call-now-option-hint">{opt.hint}</span>
            </button>
          ))}
        </div>

        <button type="button" className="btn btn--ghost btn--sm crm-modal-skip" onClick={onClose} disabled={loading}>
          Cancel
        </button>
      </div>
    </div>
  )

  return createPortal(modal, document.body)
}
