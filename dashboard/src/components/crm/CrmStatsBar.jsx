import React from 'react'
import { MetricBlock } from '../ui/MetricBlock.jsx'

export function CrmStatsBar({ stats, dueCount, alertCounts = null, compact = false }) {
  if (!stats) return null
  return (
    <div className={`crm-stats-bar${compact ? ' crm-stats-bar--compact' : ''}`} role="status">
      <MetricBlock variant="inline" label="Leads today" value={stats.leads_today ?? 0} />
      <MetricBlock variant="inline" label="Replied" value={stats.replied_users ?? 0} />
      <MetricBlock variant="inline" label="Converted" value={stats.converted_users ?? 0} tone="success" />
      {(stats.blocked_users ?? stats.spam_users ?? 0) > 0 && (
        <MetricBlock variant="inline" label="Blocked" value={stats.blocked_users ?? stats.spam_users} tone="danger" />
      )}
      {(alertCounts?.aggressive ?? 0) > 0 && (
        <MetricBlock variant="inline" label="Urgent" value={alertCounts.aggressive} tone="danger" />
      )}
      {(alertCounts?.buzzer ?? 0) > 0 && (
        <MetricBlock variant="inline" label="Delayed" value={alertCounts.buzzer} tone="warning" />
      )}
      {(alertCounts?.soft ?? 0) > 0 && (
        <MetricBlock variant="inline" label="Waiting" value={alertCounts.soft} tone="warning" />
      )}
      {dueCount > 0 && (
        <MetricBlock variant="inline" label={`Follow-up${dueCount !== 1 ? 's' : ''} due`} value={dueCount} tone="warning" />
      )}
    </div>
  )
}
