import React from 'react'
import { Button } from './ui/Button.jsx'
import { accountPrimaryMode } from '../utils/accountUi.js'

/**
 * Single row of Start/Stop actions for the account’s active mode(s).
 */
export function AccountPrimaryActions({
  slot,
  postingModeConfig,
  postingModes = {},
  accountStates = {},
  acctState = {},
  forwardJob = null,
  onShutdown = false,
  onStart,
  onStop,
  accountActionLoading = null,
  forcedMode = null,
  className = '',
}) {
  const cfg = postingModeConfig || postingModes?.[slot] || {}
  const fwdDispatch = cfg.forwarding?.forward_dispatch === 'manual' ? 'manual' : 'auto'
  const isManualForward = fwdDispatch !== 'auto'

  const campRt = acctState?.campaign || {}
  const fwdRt = acctState?.forwarding || {}
  const campRunning = !!(campRt.running ?? acctState?.campaign_running)
  const forwardCycleRunning = forwardJob?.status === 'running'
  const fwdRunning = isManualForward
    ? forwardCycleRunning
    : !!(fwdRt.running ?? acctState?.forwarding_running)

  const campStartLoading = accountActionLoading === `${slot}:campaign:start`
  const campStopLoading = accountActionLoading === `${slot}:campaign:stop`
  const fwdStartLoading = accountActionLoading === `${slot}:forwarding:start`
  const fwdStopLoading = accountActionLoading === `${slot}:forwarding:stop`

  const mode = forcedMode || accountPrimaryMode(accountStates, slot, postingModes)

  if (mode === 'off') {
    return (
      <p className={`acct-primary-actions acct-primary-actions--off${className ? ` ${className}` : ''}`}>
        Pick <strong>Campaign</strong> or <strong>Forwarding</strong> above to enable this account.
      </p>
    )
  }

  function campaignBtn() {
    if (!campRunning) {
      return (
        <Button
          variant="success"
          size="md"
          className="acct-primary-actions__btn"
          onClick={() => onStart?.(slot, false, 'campaign')}
          disabled={campStartLoading || onShutdown}
          loading={campStartLoading}
          loadingLabel="…"
        >
          ▶ Start campaign
        </Button>
      )
    }
    return (
      <Button
        variant="danger"
        size="md"
        className="acct-primary-actions__btn"
        onClick={() => onStop?.(slot, 'campaign')}
        disabled={campStopLoading}
        loading={campStopLoading}
        loadingLabel="…"
      >
        ⏹ Stop campaign
      </Button>
    )
  }

  function forwardBtn() {
    if (isManualForward) {
      return (
        <span className="acct-primary-actions__hint" title="Open manual send panel below">
          Manual forward — select groups below, then Send
        </span>
      )
    }
    if (!fwdRunning) {
      return (
        <Button
          variant="success"
          size="md"
          className="acct-primary-actions__btn"
          onClick={() => onStart?.(slot, false, 'forwarding')}
          disabled={fwdStartLoading || onShutdown}
          loading={fwdStartLoading}
          loadingLabel="…"
        >
          ▶ Start forwarding
        </Button>
      )
    }
    return (
      <Button
        variant="danger"
        size="md"
        className="acct-primary-actions__btn"
        onClick={() => onStop?.(slot, 'forwarding')}
        disabled={fwdStopLoading}
        loading={fwdStopLoading}
        loadingLabel="…"
      >
        ⏹ Stop forwarding
      </Button>
    )
  }

  return (
    <div className={`acct-primary-actions${className ? ` ${className}` : ''}`}>
      {mode === 'campaign' && campaignBtn()}
      {mode === 'forwarding' && forwardBtn()}
    </div>
  )
}
