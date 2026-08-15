import React from 'react'
import { useDialogA11y } from '../../hooks/useDialogA11y.js'

const OUTCOMES = [
  { id: 'interested', label: 'Interested' },
  { id: 'not_interested', label: 'Not Interested' },
  { id: 'follow_up', label: 'Follow-up' },
]

export function CallOutcomeModal({ open, leadName, onSelect, onDismiss, saving }) {
  // This dialog had no Escape handling and no focus management at all.
  const dialogRef = useDialogA11y(open, onDismiss)

  if (!open) return null

  return (
    <div className="crm-modal-backdrop" role="presentation" onClick={onDismiss}>
      <div
        ref={dialogRef}
        className="crm-modal crm-modal--compact"
        role="dialog"
        aria-modal="true"
        aria-labelledby="call-outcome-title"
        onClick={e => e.stopPropagation()}
      >
        <h3 id="call-outcome-title" className="crm-modal-title">Mark call outcome</h3>
        <p className="crm-modal-sub">
          Call time passed{leadName ? ` · ${leadName}` : ''}. How did it go?
        </p>
        <div className="crm-outcome-btns">
          {OUTCOMES.map(o => (
            <button
              key={o.id}
              type="button"
              className="btn btn--ghost btn--block"
              disabled={saving}
              onClick={() => onSelect(o.id)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn--ghost btn--sm crm-modal-skip" onClick={onDismiss} disabled={saving}>
          Skip for now
        </button>
      </div>
    </div>
  )
}
