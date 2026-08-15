import { getMaxReplyAlertLevel } from '../utils/replyAlert.js'
import { isMessageSoundMuted } from '../utils/soundQuietHours.js'
import { playNotification, startNotification, stopNotification } from './notificationSounds.js'

const DM_DEDUPE_MS = 4000
const recentDms = new Map()
let ringingCallId = null
const alertedReminders = new Set()

export function notifyIncomingDm({ slot = '', messageId } = {}) {
  if (messageId != null) {
    const key = `${slot}:${messageId}`
    const now = Date.now()
    const previous = recentDms.get(key)
    if (previous != null && now - previous < DM_DEDUPE_MS) return false
    recentDms.set(key, now)
    for (const [candidate, at] of recentDms) {
      if (now - at > DM_DEDUPE_MS * 2) recentDms.delete(candidate)
    }
  }
  return playNotification('dm')
}

export function notifyIncomingCall({ callId = null } = {}) {
  const key = callId == null ? 'unknown' : String(callId)
  if (ringingCallId === key) return false
  ringingCallId = key
  return startNotification('incoming_call')
}

export function notifyCallEnded() {
  ringingCallId = null
  stopNotification('incoming_call')
  stopNotification('call_reminder')
}

export function notifyCallReminder(reminderId) {
  const key = String(reminderId ?? 'unknown')
  if (alertedReminders.has(key)) return false
  alertedReminders.add(key)
  return startNotification('call_reminder')
}

export function stopCallReminder() {
  stopNotification('call_reminder')
}

export function syncUnreadAmbience(unreadCount, inboxState = null) {
  if (isMessageSoundMuted()) {
    stopNotification('unread_ghost')
    return
  }
  const slaLevel = inboxState ? getMaxReplyAlertLevel(inboxState) : null
  if (slaLevel === 'buzzer' || slaLevel === 'aggressive') {
    stopNotification('unread_ghost')
    return
  }
  if (Math.max(0, Number(unreadCount) || 0) > 3) startNotification('unread_ghost')
  else stopNotification('unread_ghost')
}

export function stopUnreadAmbience() {
  stopNotification('unread_ghost')
}

export function __resetNotificationEvents() {
  recentDms.clear()
  alertedReminders.clear()
  ringingCallId = null
}
