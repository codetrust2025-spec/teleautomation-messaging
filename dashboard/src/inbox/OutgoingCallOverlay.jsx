import React, { useEffect, useRef, useState } from 'react'

import { createPortal } from 'react-dom'

import { avatarHue, displayInitials } from './inboxUiUtils.js'

import { isTerminalVoiceStatus, voiceStatusLabel } from './voiceCallEvents.js'



function formatDuration(sec) {

  const s = Math.max(0, Number(sec) || 0)

  const m = Math.floor(s / 60)

  const r = s % 60

  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `0:${String(r).padStart(2, '0')}`

}



export function OutgoingCallOverlay({

  open,

  name,

  seed,

  channelLabel,

  status = 'ringing',

  muted = true,

  error,

  durationSec = 0,

  onMinimize,

  onDecline,

  onToggleMute,

  onDismiss,

}) {

  const [tick, setTick] = useState(0)

  const activeSinceRef = useRef(null)



  useEffect(() => {

    if (!open) return undefined

    const onKey = e => {

      if (e.key === 'Escape') onMinimize?.()

    }

    document.addEventListener('keydown', onKey)

    return () => document.removeEventListener('keydown', onKey)

  }, [open, onMinimize])



  useEffect(() => {

    if (status === 'active') {

      if (!activeSinceRef.current) {

        activeSinceRef.current = Date.now() - durationSec * 1000

      }

      const id = window.setInterval(() => setTick(t => t + 1), 1000)

      return () => clearInterval(id)

    }

    activeSinceRef.current = null

    return undefined

  }, [status, durationSec])



  if (!open) return null



  const hue = avatarHue(seed)

  const terminal = isTerminalVoiceStatus(status)

  const statusText = voiceStatusLabel(status, { error })

  const subline = channelLabel ? `via ${channelLabel}` : ''

  const liveSec = status === 'active' && activeSinceRef.current

    ? Math.floor((Date.now() - activeSinceRef.current) / 1000)

    : durationSec

  const hint = !error && status === 'ringing'

    ? 'Lead phone ringing — keep Telegram open on the business phone'

    : !error && status === 'connecting'

      ? 'Lead picked up — finishing connection…'

      : !error && status === 'active'

        ? 'Call connected — speak on the business phone Telegram app'

        : ''



  const modal = (

    <div className="tg-call-overlay-root" role="presentation">

      <div

        className={`tg-call-overlay-card${status === 'ringing' ? ' tg-call-overlay-card--pulse' : ''}`}

        role="dialog"

        aria-modal="true"

        aria-labelledby="tg-call-title"

      >

        <header className="tg-call-overlay-head">

          <button

            type="button"

            className="tg-call-overlay-icon-btn"

            onClick={onMinimize}

            aria-label="Minimize call"

            title="Minimize"

          >

            ✕

          </button>

          <div className="tg-call-overlay-head-actions">

            <button

              type="button"

              className="tg-call-overlay-icon-btn"

              onClick={onMinimize}

              aria-label="Picture in picture"

              title="Minimize"

            >

              ⧉

            </button>

          </div>

        </header>



        <div className="tg-call-overlay-body">

          <span

            className="tg-call-overlay-avatar"

            style={{ '--tg-avatar-hue': hue }}

            aria-hidden

          >

            {displayInitials(name)}

          </span>

          <h2 id="tg-call-title" className="tg-call-overlay-name">{name}</h2>

          <p className="tg-call-overlay-status">

            {statusText}

            {status === 'active' ? (

              <span className="tg-call-overlay-timer"> · {formatDuration(liveSec)}</span>

            ) : null}

          </p>

          {subline ? <p className="tg-call-overlay-channel">{subline}</p> : null}

          {hint ? <p className="tg-call-overlay-hint">{hint}</p> : null}

        </div>



        <footer className="tg-call-overlay-controls">

          <button type="button" className="tg-call-ctrl" disabled title="Video in Telegram app">

            <span className="tg-call-ctrl-icon tg-call-ctrl-icon--cam" aria-hidden />

            <span className="tg-call-ctrl-label">Camera</span>

          </button>

          <button type="button" className="tg-call-ctrl" disabled title="Screen share in Telegram app">

            <span className="tg-call-ctrl-icon tg-call-ctrl-icon--screen" aria-hidden />

            <span className="tg-call-ctrl-label">Screen</span>

          </button>

          <button

            type="button"

            className={`tg-call-ctrl tg-call-ctrl--mute${muted ? '' : ' tg-call-ctrl--mute-off'}`}

            onClick={onToggleMute}

            aria-pressed={!muted}

            title={muted ? 'Unmute (local)' : 'Mute (local)'}

          >

            <span className="tg-call-ctrl-icon tg-call-ctrl-icon--mic" aria-hidden />

            <span className="tg-call-ctrl-label">{muted ? 'Unmute' : 'Mute'}</span>

          </button>

          <button

            type="button"

            className="tg-call-ctrl tg-call-ctrl--decline"

            onClick={terminal ? (onDismiss || onDecline) : onDecline}

            aria-label={terminal ? 'Close' : 'Decline call'}

          >

            <span className="tg-call-ctrl-icon tg-call-ctrl-icon--hangup" aria-hidden />

            <span className="tg-call-ctrl-label">{terminal ? 'Close' : 'Decline'}</span>

          </button>

        </footer>

      </div>

    </div>

  )



  return createPortal(modal, document.body)

}
