import React from 'react'

export function NotesEditor({ value, onChange, onSave, saving, disabled, savedValue = '' }) {
  const dirty = !disabled && String(value ?? '') !== String(savedValue ?? '')

  return (
    <div className="crm-notes-editor">
      <label className="crm-field-label" htmlFor="crm-notes">Notes</label>
      <textarea
        id="crm-notes"
        className={`input input--textarea crm-notes-input${dirty ? ' crm-notes-input--dirty' : ''}`}
        rows={5}
        placeholder="Add notes about this lead…"
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
      />
      <button
        type="button"
        className={`btn btn--sm crm-save-notes-btn${dirty ? ' btn--primary crm-save-notes-btn--dirty' : ' btn--ghost'}`}
        onClick={onSave}
        disabled={disabled || saving || !dirty}
        aria-live="polite"
      >
        {saving ? 'Saving…' : dirty ? 'Save notes' : 'Saved'}
      </button>
    </div>
  )
}
