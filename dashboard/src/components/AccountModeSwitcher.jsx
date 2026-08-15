import React, { useMemo, useState } from 'react'
import { ResponsiveOptions } from './ui/ResponsiveOptions.jsx'
import { isCampaignEnabled, isForwardingEnabled } from '../utils/accountUi.js'
import { applyAccountPostingMode } from '../utils/accountPostingMode.js'

const MODE_OPTIONS = [
  { value: 'campaign', label: 'Campaign' },
  { value: 'forwarding', label: 'Forwarding' },
]

function activeMode(campaignOn, forwardingOn) {
  if (forwardingOn) return 'forwarding'
  if (campaignOn) return 'campaign'
  return 'campaign'
}

/**
 * One-tap primary mode for an account (replaces hunting through filters + nested tabs).
 */
export function AccountModeSwitcher({
  slot,
  postingModeConfig,
  postingModes,
  accountStates,
  onUpdated,
  onModeApplied,
  className = '',
}) {
  const cfg = postingModeConfig || postingModes?.[slot] || {}
  const campaignOn = isCampaignEnabled(accountStates, slot, postingModes || { [slot]: cfg })
  const forwardingOn = isForwardingEnabled(accountStates, slot, postingModes || { [slot]: cfg })
  const value = useMemo(() => activeMode(campaignOn, forwardingOn), [campaignOn, forwardingOn])

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function applyMode(next) {
    if (!slot || next === value) return
    setLoading(true)
    setError('')
    const result = await applyAccountPostingMode(slot, next)
    if (!result.ok) {
      setError(result.error)
    } else {
      onUpdated?.()
      onModeApplied?.(next)
    }
    setLoading(false)
  }

  if (!slot) {
    return (
      <p className={`stat-hint account-mode-switcher-hint${className ? ` ${className}` : ''}`}>
        Pick an account first.
      </p>
    )
  }

  return (
    <div className={`account-mode-switcher${className ? ` ${className}` : ''}`}>
      <ResponsiveOptions
        className="account-mode-switcher__control"
        segmentedClassName="account-mode-switcher__segments"
        label="Forward or Campaign"
        options={MODE_OPTIONS.map(o => ({
          ...o,
          label: o.value === 'forwarding' ? 'Forwarding' : 'Campaign',
          disabled: loading,
        }))}
        value={value}
        onChange={applyMode}
        role="tablist"
        compactColumns={2}
      />
      <p className="account-mode-switcher__help">
        Tap <strong>Forwarding</strong> or <strong>Campaign</strong>, then <strong>Start</strong> in step 3.
      </p>
      {error && <p className="field-error account-mode-switcher__error">{error}</p>}
    </div>
  )
}
