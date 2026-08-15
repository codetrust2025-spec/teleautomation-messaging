import React, { useEffect, useMemo, useState } from 'react'
import { useDialogA11y } from '../../hooks/useDialogA11y.js'
import { createPortal } from 'react-dom'
import { CALL_TYPES, toLocalISO } from '../../utils/calls.js'

function defaultDateTime() {
  const d = new Date()
  d.setMinutes(d.getMinutes() + 30 - (d.getMinutes() % 15))
  return {
    date: d.toISOString().slice(0, 10),
    time: d.toTimeString().slice(0, 5),
  }
}

export function ScheduleCallModal({ open, leadName, onConfirm, onClose, saving }) {
  // Focus in, Tab trapped, focus restored to the trigger. Escape stays
  // below so this dialog's own guard keeps its exact behaviour.
  const dialogRef = useDialogA11y(open, onClose, { closeOnEscape: false })

  const defaults = useMemo(() => defaultDateTime(), [open])
  const [date, setDate] = useState(defaults.date)
  const [time, setTime] = useState(defaults.time)
  const [callType, setCallType] = useState('telegram')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    if (!open) return
    const d = defaultDateTime()
    setDate(d.date)
    setTime(d.time)
    setCallType('telegram')
    setNotes('')
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const onKey = e => {
      if (e.key === 'Escape' && !saving) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, saving, onClose])

  if (!open) return null

  const iso = toLocalISO(date, time)
  const valid = Boolean(iso)

  const modal = (
    <div className="crm-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="crm-modal"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="schedule-call-title"
        onClick={e => e.stopPropagation()}
      >
        <h3 id="schedule-call-title" className="crm-modal-title">
          Schedule call{leadName ? ` · ${leadName}` : ''}
        </h3>

        <label className="crm-modal-field">
          <span className="crm-field-label">Date</span>
          <input
            type="date"
            className="input"
            value={date}
            min={new Date().toISOString().slice(0, 10)}
            onChange={e => setDate(e.target.value)}
          />
        </label>

        <label className="crm-modal-field">
          <span className="crm-field-label">Time</span>
          <input
            type="time"
            className="input"
            value={time}
            onChange={e => setTime(e.target.value)}
          />
        </label>

        <fieldset className="crm-modal-field crm-call-type-field">
          <legend className="crm-field-label">Call type</legend>
          <div className="crm-call-type-options">
            {CALL_TYPES.map(t => (
              <label key={t.id} className="crm-call-type-option">
                <input
                  type="radio"
                  name="call_type"
                  value={t.id}
                  checked={callType === t.id}
                  onChange={() => setCallType(t.id)}
                />
                {t.label}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="crm-modal-field">
          <span className="crm-field-label">Notes (optional)</span>
          <input
            type="text"
            className="input"
            placeholder="e.g. Discuss pricing"
            value={notes}
            onChange={e => setNotes(e.target.value)}
          />
        </label>

        <div className="crm-modal-actions">
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={!valid || saving}
            onClick={() => onConfirm({ scheduled_time: iso, call_type: callType, notes })}
          >
            {saving ? 'Scheduling…' : 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  )

  return createPortal(modal, document.body)
}
