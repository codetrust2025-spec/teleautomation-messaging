import React from 'react'

export function CallReminderBanner({ reminders, onOpen }) {
  if (!reminders?.length) return null
  const top = reminders[0]
  const name = top.name || top.username || top.user_id
  const mins = top.minutes_until ?? 0

  return (
    <div className="crm-call-reminder-banner" role="alert">
      <span>
        Call with <strong>{name}</strong>
        {mins <= 0 ? ' now' : ` in ${mins} minute${mins === 1 ? '' : 's'}`}
        {' · '}{top.call_type}
      </span>
      <button type="button" className="btn btn--sm btn--primary" onClick={() => onOpen?.(top)}>
        Open chat
      </button>
    </div>
  )
}
