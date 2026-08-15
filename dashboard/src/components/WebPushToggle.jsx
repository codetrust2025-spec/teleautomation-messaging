import React, { useEffect, useState } from 'react'
import {
  disableWebPush,
  enableWebPush,
  isStandalonePwa,
  isWebPushEnabled,
  isWebPushSupported,
  notificationPermission,
} from '../utils/webPush.js'

export function WebPushToggle({ compact = false }) {
  const supported = isWebPushSupported()
  const [on, setOn] = useState(() => isWebPushEnabled())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [perm, setPerm] = useState(() => notificationPermission())

  useEffect(() => {
    const sync = () => {
      setOn(isWebPushEnabled())
      setPerm(notificationPermission())
    }
    window.addEventListener('web-push-toggle', sync)
    return () => window.removeEventListener('web-push-toggle', sync)
  }, [])

  if (!supported) return null

  const standalone = isStandalonePwa()
  const title = standalone
    ? 'Lock-screen alerts when the app is closed (iPhone/Android Home Screen)'
    : 'Lock-screen alerts — add TeleAutomation to Home Screen first on iPhone'

  async function handleToggle(checked) {
    setError('')
    setBusy(true)
    try {
      if (checked) {
        await enableWebPush()
        setPerm(notificationPermission())
        setOn(true)
      } else {
        await disableWebPush()
        setOn(false)
      }
    } catch (e) {
      setOn(false)
      setError(e?.message || 'Could not update push notifications')
    } finally {
      setBusy(false)
    }
  }

  const active = on && perm === 'granted'

  return (
    <div className={`web-push-toggle${compact ? ' web-push-toggle--compact' : ''}`}>
      <label className="crm-buzzer-toggle" title={title}>
        <input
          type="checkbox"
          className="crm-buzzer-toggle-input"
          checked={active}
          disabled={busy}
          onChange={e => handleToggle(e.target.checked)}
        />
        <span className="crm-buzzer-toggle-label">
          {compact
            ? (active ? '🔔 Push' : '🔕 Push')
            : (active ? '🔔 Lock-screen ON' : '🔕 Lock-screen OFF')}
        </span>
      </label>
      {!standalone && perm === 'default' && (
        <span className="web-push-hint">Add to Home Screen for iPhone push</span>
      )}
      {error && <span className="web-push-error">{error}</span>}
    </div>
  )
}
