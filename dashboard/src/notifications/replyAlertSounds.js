/**
 * CRM reply-SLA tiers driven from inbox state.
 *
 * Thresholds, tier names and conversation selection are untouched — they still
 * come from utils/replyAlert.js. What changed is that the three tiers now play
 * three independent sounds (marimba / double-pulse / siren) instead of one
 * buzzer with an `aggressive` flag, and that this runs from the global sound
 * manager rather than from InboxPanel, so a delayed reply is heard on any page.
 */

import {
  AGGRESSIVE_BEEP_INTERVAL_MS,
  BUZZER_BEEP_INTERVAL_MS,
  conversationAlertKey,
  getMaxReplyAlertLevel,
  isBuzzerAlertsEnabled,
  listAlertConversations,
} from '../utils/replyAlert.js'
import { isMessageSoundMuted } from '../utils/soundQuietHours.js'
import { startNotification, playNotification, stopNotification } from './notificationSounds.js'
import { startSla10Pulse, stopSla10Pulse, isSla10Looping } from './sounds/sla10Pulse.js'
import { startSla20Siren, stopSla20Siren, isSla20Looping } from './sounds/sla20Siren.js'

/** Conversations already given their one-off 5-minute nudge. */
const softNotified = new Set()

function stopAllLoops() {
  stopSla10Pulse()
  stopSla20Siren()
}

function pruneSoftNotified(activeKeys) {
  for (const key of [...softNotified]) {
    if (!activeKeys.has(key)) softNotified.delete(key)
  }
}

/**
 * Evaluate every conversation and drive the tier sounds.
 *
 * Only one tier loop runs at a time: the loudest tier present wins, exactly as
 * before. Escalating from 10 to 20 minutes stops the pulse before starting the
 * siren, so the two never overlap into a third, accidental sound.
 */
export function syncReplyAlertSounds(inboxState) {
  if (!isBuzzerAlertsEnabled() || isMessageSoundMuted()) {
    stopAllLoops()
    return
  }

  const items = listAlertConversations(inboxState)
  const activeKeys = new Set(items.map((item) => conversationAlertKey(item.conv)))
  pruneSoftNotified(activeKeys)

  for (const item of items) {
    if (item.level !== 'soft') continue
    const key = conversationAlertKey(item.conv)
    if (softNotified.has(key)) continue
    softNotified.add(key)
    playNotification('sla_5')
  }

  const maxLevel = getMaxReplyAlertLevel(inboxState)
  if (maxLevel === 'aggressive') {
    stopSla10Pulse()
    if (!isSla20Looping()) startSla20Siren(AGGRESSIVE_BEEP_INTERVAL_MS)
  } else if (maxLevel === 'buzzer') {
    stopSla20Siren()
    if (!isSla10Looping()) startSla10Pulse(BUZZER_BEEP_INTERVAL_MS)
  } else {
    stopAllLoops()
  }
}

/** Release loops and per-conversation memory (unmount, sign-out, tests). */
export function resetReplyAlertSounds() {
  stopAllLoops()
  softNotified.clear()
}

// Re-exported so callers never reach past this module into the raw loops.
export { startNotification, stopNotification }
