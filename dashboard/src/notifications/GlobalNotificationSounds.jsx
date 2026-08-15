import { useEffect } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import { REPLY_CHECK_INTERVAL_MS } from '../utils/replyAlert.js'
import {
  notifyCallReminder,
  stopCallReminder,
  stopUnreadAmbience,
  syncUnreadAmbience,
} from './notificationEvents.js'
import { resetReplyAlertSounds, syncReplyAlertSounds } from './replyAlertSounds.js'
import { installSoundPreview } from './soundPreview.js'

const AMBIENCE_RECHECK_MS = 60000

export function GlobalNotificationSounds({ inboxState = null, inboxUnreadTotal = 0, crmState = null }) {
  const { authenticated } = useAuth()

  useEffect(() => {
    if (import.meta.env?.DEV) installSoundPreview()
  }, [])

  useEffect(() => {
    if (!authenticated) return undefined
    const resync = () => syncReplyAlertSounds(inboxState)
    resync()
    const tick = window.setInterval(resync, REPLY_CHECK_INTERVAL_MS)
    window.addEventListener('crm-buzzer-toggle', resync)
    window.addEventListener('sound-quiet-hours-change', resync)
    return () => {
      window.clearInterval(tick)
      window.removeEventListener('crm-buzzer-toggle', resync)
      window.removeEventListener('sound-quiet-hours-change', resync)
    }
  }, [authenticated, inboxState])

  useEffect(() => {
    if (!authenticated) return undefined
    const resync = () => syncUnreadAmbience(inboxUnreadTotal, inboxState)
    resync()
    const tick = window.setInterval(resync, AMBIENCE_RECHECK_MS)
    window.addEventListener('sound-quiet-hours-change', resync)
    window.addEventListener('crm-buzzer-toggle', resync)
    return () => {
      window.clearInterval(tick)
      window.removeEventListener('sound-quiet-hours-change', resync)
      window.removeEventListener('crm-buzzer-toggle', resync)
    }
  }, [authenticated, inboxUnreadTotal, inboxState])

  useEffect(() => {
    if (!authenticated) return undefined
    for (const reminder of crmState?.call_reminders || []) {
      notifyCallReminder(reminder.id || `${reminder.account_id}:${reminder.user_id}`)
    }
    return undefined
  }, [authenticated, crmState?.call_reminders])

  useEffect(() => {
    if (authenticated) return undefined
    stopUnreadAmbience()
    resetReplyAlertSounds()
    return undefined
  }, [authenticated])

  useEffect(() => () => {
    stopUnreadAmbience()
    stopCallReminder()
    resetReplyAlertSounds()
  }, [])

  return null
}

export default GlobalNotificationSounds
