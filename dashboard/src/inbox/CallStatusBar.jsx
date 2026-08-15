import React from 'react'

import { avatarHue, displayInitials } from './inboxUiUtils.js'



export function CallStatusBar({

  name,

  seed,

  statusLabel = 'Ringing…',

  onExpand,

  onEnd,

}) {

  const hue = avatarHue(seed)



  return (

    <div className="tg-call-status-bar" role="status">

      <button type="button" className="tg-call-status-tap" onClick={onExpand}>

        <span className="tg-call-status-mic" aria-hidden />

        <span

          className="tg-call-status-avatar"

          style={{ '--tg-avatar-hue': hue }}

          aria-hidden

        >

          {displayInitials(name)}

        </span>

        <span className="tg-call-status-text">

          <strong>{name}</strong>

          <span>{statusLabel}</span>

        </span>

      </button>

      <button

        type="button"

        className="tg-call-status-end"

        onClick={onEnd}

        aria-label="End call"

        title="End call"

      >

        <span className="tg-call-status-end-icon" aria-hidden />

      </button>

    </div>

  )

}
