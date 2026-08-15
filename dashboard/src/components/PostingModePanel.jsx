import React, { useEffect, useState } from 'react'

import { API } from '../config.js'

import { Button } from './ui/Button.jsx'

import { ButtonContent } from '../Loader.jsx'

import { SegmentedControl } from './ui/SegmentedControl.jsx'

import { accountLabel, isCampaignEnabled, isForwardingEnabled } from '../utils/accountUi.js'
import { forwardTmeUrlFromConfig } from '../utils/forwardAccountUtils.js'

const DISPATCH_OPTIONS = [
  { value: 'auto', label: '24/7 auto' },
  { value: 'manual', label: 'Manual Send' },
]



/**

 * Independent Campaign and Forwarding enablement + forwarding source config.

 */

export function PostingModePanel({

  slot,

  postingModeConfig,

  postingModes,

  accountStates,

  acctRunning,

  onUpdated,

  onStartForward,

  onStopForward,

  setupFilter = 'all',
  layout = 'full',
  primaryMode = null,

}) {

  const cfg = postingModeConfig || postingModes?.[slot] || {}

  const fwd = cfg.forwarding || {}

  const sourceType = fwd.source_type === 'telegram_post' ? 'telegram_post' : 'template'

  const campaignOn = isCampaignEnabled(accountStates, slot, postingModes || { [slot]: cfg })

  const forwardingOn = isForwardingEnabled(accountStates, slot, postingModes || { [slot]: cfg })
  const forwardDispatch = fwd.forward_dispatch === 'manual' ? 'manual' : 'auto'
  const fwdState = accountStates?.[slot] || {}
  const fwdRunning = !!(
    fwdState.forwarding_running
    || fwdState.forwarding?.running
  )

  const [sourceUrl, setSourceUrl] = useState('')

  useEffect(() => {
    setSourceUrl(forwardTmeUrlFromConfig(fwd))
    setError('')
  }, [slot, fwd.source_peer, fwd.source_message_id, fwd.source_label, fwd.source_type])

  const [toggleLoading, setToggleLoading] = useState(null)

  const [sourceLoading, setSourceLoading] = useState(false)

  const [sourceTypeLoading, setSourceTypeLoading] = useState(false)

  const [error, setError] = useState('')



  async function patchFeatures(patch) {

    setToggleLoading(Object.keys(patch).join(','))

    setError('')

    try {

      const res = await fetch(`${API}/account/${slot}/posting-mode`, {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(patch),

      })

      const data = await res.json()

      if (data.status === 'error') {

        setError(data.message || 'Could not update features')

        return

      }

      onUpdated?.()

    } catch (e) {

      setError(e.message || 'Request failed')

    } finally {

      setToggleLoading(null)

    }

  }



  async function setForwardSourceType(nextType) {

    if (nextType === sourceType) return

    setSourceTypeLoading(true)

    setError('')

    try {

      const res = await fetch(`${API}/account/${slot}/posting-mode`, {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ forward_source_type: nextType }),

      })

      const data = await res.json()

      if (data.status === 'error') {

        setError(data.message || 'Could not change source type')

        return

      }

      onUpdated?.()

    } catch (e) {

      setError(e.message || 'Request failed')

    } finally {

      setSourceTypeLoading(false)

    }

  }



  async function saveSource(e) {

    e.preventDefault()

    const url = sourceUrl.trim()

    if (!url) {

      setError('Paste a t.me post link (channel/message id)')

      return

    }

    setSourceLoading(true)

    setError('')

    try {

      const res = await fetch(`${API}/account/${slot}/forwarding/source`, {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ source_url: url }),

      })

      const data = await res.json()

      if (data.status === 'error') {

        setError(data.message || 'Could not save source')

        return

      }

      setSourceUrl('')

      onUpdated?.()

    } catch (err) {

      setError(err.message || 'Request failed')

    } finally {

      setSourceLoading(false)

    }

  }



  const configured = !!fwd.configured

  const busy = toggleLoading || sourceTypeLoading

  const simple = layout === 'simple'
  const mode = primaryMode || (forwardingOn ? 'forwarding' : campaignOn ? 'campaign' : 'off')

  const showCampaign = simple
    ? mode === 'campaign'
    : (setupFilter === 'all' || setupFilter === 'campaign')

  const showForwarding = simple
    ? mode === 'forwarding'
    : (setupFilter === 'all' || setupFilter === 'forwarding')

  const panelTitle = setupFilter === 'forwarding'

    ? 'Forwarding setup'

    : setupFilter === 'campaign'

      ? 'Campaign setup'

      : 'Features'



  return (

    <div className={`posting-mode-panel posting-mode-panel--segregated${setupFilter !== 'all' ? ` posting-mode-panel--${setupFilter}-only` : ''}${simple ? ' posting-mode-panel--simple' : ''}`}>

      {!simple && (
        <div className="posting-mode-panel__head">
          <span className="posting-mode-panel__title">{panelTitle}</span>
          <span className="posting-mode-panel__hint">
            Enable campaign and/or forwarding, then configure message source.
          </span>
        </div>
      )}

      <div className="posting-mode-stack">

        {showCampaign && (

          <section

            className={`posting-mode-section posting-mode-section--campaign${campaignOn ? ' posting-mode-section--active' : ''}`}

          >

            <header className="posting-mode-section__head">
              <h4 className="posting-mode-section__title">Campaign message</h4>
              {!simple && (
                <label className="posting-mode-enable">
                  <input
                    type="checkbox"
                    checked={campaignOn}
                    disabled={!!toggleLoading}
                    onChange={e => patchFeatures({
                      campaign_enabled: e.target.checked,
                      ...(e.target.checked ? { forwarding_enabled: false } : {}),
                    })}
                  />
                  <span>Enabled</span>
                </label>
              )}
            </header>
            {!simple && (
              <p className="posting-mode-panel__desc">
                Posts to your master-list slice on a schedule.
              </p>
            )}

          </section>

        )}



        {showForwarding && (

          <section

            className={`posting-mode-section posting-mode-section--forwarding${forwardingOn ? ' posting-mode-section--active' : ''}`}

          >

            <header className="posting-mode-section__head">
              <h4 className="posting-mode-section__title">Forwarding setup</h4>
              {!simple && (
                <label className="posting-mode-enable">
                  <input
                    type="checkbox"
                    checked={forwardingOn}
                    disabled={!!toggleLoading}
                    onChange={e => patchFeatures({
                      forwarding_enabled: e.target.checked,
                      ...(e.target.checked
                        ? { campaign_enabled: false, forward_dispatch: 'auto' }
                        : {}),
                    })}
                  />
                  <span>Enabled</span>
                </label>
              )}
            </header>

            {forwardingOn && (
              <div className="posting-mode-panel__forward">
                <SegmentedControl
                  className="posting-mode-dispatch-tabs"
                  label="How to forward"
                  options={DISPATCH_OPTIONS}
                  value={forwardDispatch}
                  onChange={v => patchFeatures({ forward_dispatch: v })}
                  role="tablist"
                />
                {simple && forwardDispatch === 'auto' && (
                  <p className="stat-hint posting-mode-panel__desc">
                    24/7 auto — ~60–100 groups per tick, then 10–30 min rest. Use <strong>Start forwarding</strong> above.
                  </p>
                )}
                {simple && forwardDispatch === 'manual' && (
                  <p className="stat-hint posting-mode-panel__desc">
                    Pick groups in the manual panel below, then <strong>Send</strong>.
                  </p>
                )}
                {!simple && forwardDispatch === 'auto' && (
                  <div className="posting-mode-start-24-7 btn-row">
                    {!fwdRunning ? (
                      <Button
                        type="button"
                        variant="success"
                        size="sm"
                        disabled={!configured || !!toggleLoading || !onStartForward}
                        onClick={() => onStartForward?.(slot)}
                        title={configured ? 'Start the 24/7 forward loop' : 'Set message source first'}
                      >
                        ▶ Start 24/7 forwarding
                      </Button>
                    ) : (
                      <Button
                        type="button"
                        variant="danger"
                        size="sm"
                        disabled={!!toggleLoading || !onStopForward}
                        onClick={() => onStopForward?.(slot)}
                      >
                        ⏹ Stop 24/7 forwarding
                      </Button>
                    )}
                    {!configured && (
                      <span className="stat-hint">Set template or t.me source below first.</span>
                    )}
                  </div>
                )}

                <div

                  className="posting-mode-panel__modes posting-mode-panel__source-types"

                  role="group"

                  aria-label="Forwarding content source"

                >

                  <button

                    type="button"

                    className={`posting-mode-btn${sourceType === 'template' ? ' posting-mode-btn--active' : ''}`}

                    disabled={busy}

                    onClick={() => setForwardSourceType('template')}

                  >

                    Message to send

                  </button>

                  <button

                    type="button"

                    className={`posting-mode-btn${sourceType === 'telegram_post' ? ' posting-mode-btn--active' : ''}`}

                    disabled={busy}

                    onClick={() => setForwardSourceType('telegram_post')}

                  >

                    t.me post link

                  </button>

                </div>



                {sourceType === 'template' && (

                  <>

                    {configured ? (

                      <p className="posting-mode-panel__source-ok">

                        Uses <strong>{accountLabel(slot)}</strong>
                        {' '}
                        own template below — not shared with other accounts (rewrite if enabled).

                      </p>

                    ) : (

                      <p className="posting-mode-panel__source-warn">

                        Open <strong>Message to send</strong> below and save text for <strong>{accountLabel(slot)}</strong> only.

                      </p>

                    )}

                  </>

                )}



                {sourceType === 'telegram_post' && (

                  <>

                    {configured ? (

                      <p className="posting-mode-panel__source-ok">

                        Saved for <strong>{accountLabel(slot)}</strong> only:{' '}
                        <strong>{fwd.source_label || fwd.source_peer}</strong>
                        {' '}· msg #{fwd.source_message_id}

                      </p>

                    ) : (

                      <p className="posting-mode-panel__source-warn">

                        Paste this account’s post link only (not used by other accounts).

                      </p>

                    )}

                    <form className="posting-mode-panel__form" onSubmit={saveSource}>

                      <label className="field-label" htmlFor={`fwd-src-${slot}`}>

                        {accountLabel(slot)} — t.me post link

                      </label>

                      <input

                        id={`fwd-src-${slot}`}

                        className="input"

                        type="url"

                        placeholder="https://t.me/yourchannel/123"

                        value={sourceUrl}

                        onChange={e => setSourceUrl(e.target.value)}

                        disabled={sourceLoading}

                      />

                      <Button

                        type="submit"

                        variant="primary"

                        size="sm"

                        disabled={sourceLoading || !sourceUrl.trim()}

                      >

                        <ButtonContent loading={sourceLoading} loadingLabel="Saving…">

                          Save source

                        </ButtonContent>

                      </Button>

                    </form>

                  </>

                )}

              </div>

            )}

          </section>

        )}

      </div>



      {error && <p className="field-error">{error}</p>}

    </div>

  )

}
