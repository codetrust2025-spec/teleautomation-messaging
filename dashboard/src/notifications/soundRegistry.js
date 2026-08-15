import { playDmChime } from './sounds/dmChime.js'
import { playUnreadGhostPreview, startUnreadGhost, stopUnreadGhost } from './sounds/unreadGhost.js'
import { startCallRing, stopCallRing } from './sounds/callRing.js'
import { playCallReminder, startCallReminder, stopCallReminder } from './sounds/callReminder.js'
import { playSla5Marimba } from './sounds/sla5Marimba.js'
import { playSla10Pulse, startSla10Pulse, stopSla10Pulse } from './sounds/sla10Pulse.js'
import { playSla20Siren, startSla20Siren, stopSla20Siren } from './sounds/sla20Siren.js'

export const NOTIFICATION_IDS = [
  'dm',
  'unread_ghost',
  'incoming_call',
  'call_reminder',
  'sla_5',
  'sla_10',
  'sla_20',
]

export const NOTIFICATION_SOUNDS = {
  dm: {
    id: 'dm', label: 'New incoming DM', play: playDmChime,
    start: null, stop: null, loop: false, quietHours: true, crmToggle: false,
    dedupe: 'slot + message id, 4s window',
  },
  unread_ghost: {
    id: 'unread_ghost', label: 'Inbox unread > 3', play: playUnreadGhostPreview,
    start: startUnreadGhost, stop: stopUnreadGhost, loop: true,
    quietHours: true, crmToggle: false,
    dedupe: 'state-driven unread threshold',
  },
  incoming_call: {
    id: 'incoming_call', label: 'Incoming voice call', play: startCallRing,
    start: startCallRing, stop: stopCallRing, loop: true,
    quietHours: true, crmToggle: false, dedupe: 'call id',
  },
  call_reminder: {
    id: 'call_reminder', label: 'Scheduled call reminder', play: playCallReminder,
    start: startCallReminder, stop: stopCallReminder, loop: true,
    quietHours: true, crmToggle: false, dedupe: 'reminder id per session',
  },
  sla_5: {
    id: 'sla_5', label: 'Reply SLA — 5 minutes', play: playSla5Marimba,
    start: null, stop: null, loop: false, quietHours: true, crmToggle: true,
    dedupe: 'conversation key while overdue',
  },
  sla_10: {
    id: 'sla_10', label: 'Reply SLA — 10 minutes', play: playSla10Pulse,
    start: startSla10Pulse, stop: stopSla10Pulse, loop: true,
    quietHours: true, crmToggle: true, dedupe: 'highest active SLA tier',
  },
  sla_20: {
    id: 'sla_20', label: 'Reply SLA — 20 minutes', play: playSla20Siren,
    start: startSla20Siren, stop: stopSla20Siren, loop: true,
    quietHours: true, crmToggle: true, dedupe: 'highest active SLA tier',
  },
}

export function soundEntry(id) {
  const entry = NOTIFICATION_SOUNDS[id]
  if (!entry) throw new Error(`Unknown notification sound: ${id}`)
  return entry
}
