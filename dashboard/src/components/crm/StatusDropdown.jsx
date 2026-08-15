import React from 'react'
import { CRM_STATUSES } from '../../utils/crm.js'

export function StatusDropdown({ value, onChange, disabled }) {
  return (
    <select
      className="input input--select crm-status-select"
      value={value || 'new'}
      onChange={e => onChange(e.target.value)}
      disabled={disabled}
      aria-label="Lead status"
    >
      {CRM_STATUSES.map(s => (
        <option key={s.id} value={s.id}>{s.label}</option>
      ))}
    </select>
  )
}
