import React from 'react'
import {
  formatCountdown,
  getAccountStatus,
  isHeavyRateLimit,
  sleepSummary,
} from '../utils/accountUi'
import { SubscriptionBadge } from './SubscriptionBadge.jsx'

/** Primary status line + secondary action line for account panel hierarchy. */
export function getHeroDisplay(acctState, loggedIn, currentGroup, accountStatus) {
  const status = getAccountStatus(acctState, loggedIn, accountStatus)
  const countdown = Math.max(0, Number(acctState?.next_cycle_in) || 0)
  const heavy = isHeavyRateLimit(acctState)

  if (!loggedIn) {
    return { tier: 'idle', label: 'SIGN IN', detail: 'Log in to start forwarding', pulse: false }
  }
  if (heavy) {
    const sleep = sleepSummary(acctState)
    return {
      tier: 'danger',
      label: 'RATE LIMITED',
      detail: sleep || (countdown > 0 ? `Sleep ${formatCountdown(countdown)}` : 'Account sleeping'),
      pulse: false,
    }
  }
  if (status === 'rate_limited') {
    return {
      tier: 'danger',
      label: 'RATE LIMITED',
      detail: countdown > 0 ? `Wait ${formatCountdown(countdown)}` : 'Flood wait active',
      pulse: false,
    }
  }
  if (status === 'running') {
    const group = (currentGroup || acctState?.current_group || '').replace(/^@/, '')
    if (group) {
      return {
        tier: 'success',
        label: 'RUNNING',
        detail: `Sending → @${group}`,
        pulse: true,
      }
    }
    if (countdown > 0) {
      return {
        tier: 'warn',
        label: 'WAITING',
        detail: formatCountdown(countdown),
        pulse: true,
      }
    }
    return { tier: 'success', label: 'RUNNING', detail: 'Processing groups', pulse: true }
  }
  if (status === 'stopped') {
    return { tier: 'neutral', label: 'STOPPED', detail: 'Ready to start', pulse: false }
  }
  return { tier: 'neutral', label: 'STOPPED', detail: null, pulse: false }
}

export function AccountStatusHero({ acctState, loggedIn, currentGroup, accountStatus, slotLabel, isSubscription }) {
  const hero = getHeroDisplay(acctState, loggedIn, currentGroup, accountStatus)

  return (
    <div className={`account-status-hero account-status-hero--${hero.tier}${hero.pulse ? ' account-status-hero--pulse' : ''}${isSubscription ? ' account-status-hero--subscription' : ''}`}>
      <div className="account-status-hero-main">
        <span className="account-status-hero-dot" aria-hidden />
        <span className="account-status-hero-label">{hero.label}</span>
        {isSubscription && (
          <span className="account-status-hero-sub">
            <SubscriptionBadge variant="pill" showLabel />
          </span>
        )}
      </div>
      {hero.detail && (
        <p className="account-status-hero-detail">{hero.detail}</p>
      )}
      {slotLabel && <span className="account-status-hero-slot">{slotLabel}</span>}
    </div>
  )
}
