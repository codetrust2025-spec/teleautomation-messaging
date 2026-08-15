import React from 'react'

/** Shared mark for accounts listed in subscription_accounts.json. */
export const SUBSCRIPTION_ICON = '◆'

export function SubscriptionBadge({
  variant = 'pill',
  showLabel = true,
  title = 'Subscription account (configured in subscription_accounts.json)',
}) {
  if (variant === 'icon') {
    return (
      <span className="sub-badge sub-badge--icon" title={title} aria-label={title}>
        {SUBSCRIPTION_ICON}
      </span>
    )
  }
  if (variant === 'dot') {
    return (
      <span className="sub-badge sub-badge--dot" title={title} aria-label={title}>
        <span className="sub-badge-dot" aria-hidden />
        {showLabel && <span className="sub-badge-label">Sub</span>}
      </span>
    )
  }
  return (
    <span className="sub-badge sub-badge--pill" title={title}>
      <span className="sub-badge-icon" aria-hidden>{SUBSCRIPTION_ICON}</span>
      {showLabel && <span>Subscription</span>}
    </span>
  )
}

export function AccountTypeLegend({ className = '' }) {
  return (
    <div className={`account-type-legend${className ? ` ${className}` : ''}`} role="note">
      <span className="account-type-legend-item">
        <SubscriptionBadge variant="pill" showLabel={false} />
        <span>Subscription account</span>
      </span>
      <span className="account-type-legend-item account-type-legend-item--posting">
        <span className="posting-mark" aria-hidden>●</span>
        <span>Posting account</span>
      </span>
    </div>
  )
}
