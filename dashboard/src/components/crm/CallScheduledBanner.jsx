import React from 'react'
import { callTypeLabel, formatCallScheduleTime } from '../../utils/calls.js'

export function CallScheduledBanner({ call }) {
  if (!call || call.status !== 'scheduled') return null

  return (
    <div className="crm-call-banner" role="status">
      <span className="crm-call-banner-icon" aria-hidden>📞</span>
      <span>
        Call scheduled at <strong>{formatCallScheduleTime(call.scheduled_time)}</strong>
        {' · '}{callTypeLabel(call.call_type)}
        {call.notes ? ` — ${call.notes}` : ''}
      </span>
    </div>
  )
}
