import React, { useEffect, useState } from 'react'
import { isBuzzerAlertsEnabled, setBuzzerAlertsEnabled } from '../../utils/replyAlert.js'

export function CrmBuzzerToggle({ compact = false }) {
  const [on, setOn] = useState(() => isBuzzerAlertsEnabled())

  useEffect(() => {
    const sync = () => setOn(isBuzzerAlertsEnabled())
    window.addEventListener('crm-buzzer-toggle', sync)
    return () => window.removeEventListener('crm-buzzer-toggle', sync)
  }, [])

  return (
    <label
      className={`crm-buzzer-toggle${compact ? ' crm-buzzer-toggle--compact' : ''}`}
      title="Reply alerts: 5m soft chime, 10m buzzer, 20m urgent"
    >
      <input
        type="checkbox"
        className="crm-buzzer-toggle-input"
        checked={on}
        onChange={e => {
          setBuzzerAlertsEnabled(e.target.checked)
          setOn(e.target.checked)
        }}
      />
      <span className="crm-buzzer-toggle-label">
        {compact ? (on ? '🔊' : '🔇') : (on ? '🔊 Alerts ON' : '🔇 Alerts OFF')}
      </span>
    </label>
  )
}
