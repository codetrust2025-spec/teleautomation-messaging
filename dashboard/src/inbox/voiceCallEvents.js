/** Map backend voice_call WS payloads to overlay UI status. */

const TERMINAL = new Set(['ended', 'missed', 'failed', 'declined'])

export function sessionStatusFromVoiceEvent(event, session) {
  const ev = String(event || '')
  const st = String(session?.status || '')

  if (ev === 'telegram_ringing' || ev === 'started') return 'ringing'
  if (ev === 'telegram_answered' || ev === 'connecting' || ev === 'client_joining') {
    return 'connecting'
  }
  if (ev === 'telegram_active' || ev === 'active') return 'active'
  if (ev === 'telegram_failed' || ev === 'failed') return 'failed'
  if (ev === 'telegram_ended' || ev === 'ended' || ev === 'missed') {
    return st === 'missed' ? 'missed' : 'ended'
  }
  if (TERMINAL.has(st)) return st
  if (st === 'ringing' || st === 'connecting' || st === 'active') return st
  return 'ringing'
}

export function isTerminalVoiceStatus(status) {
  return TERMINAL.has(status)
}

export function voiceStatusLabel(status, { error } = {}) {
  if (error) return error
  switch (status) {
    case 'ringing':
      return 'Ringing…'
    case 'connecting':
      return 'Connecting…'
    case 'active':
      return 'On call'
    case 'missed':
      return 'Missed call'
    case 'failed':
      return 'Could not connect'
    case 'declined':
      return 'Call declined'
    case 'ended':
      return 'Call ended'
    default:
      return 'Ringing…'
  }
}

export function voiceChannelLabel(callMode) {
  if (callMode === 'telegram') return 'Telegram'
  if (callMode === 'hybrid') return 'Telegram + link'
  if (callMode === 'browser') return 'Browser call'
  return 'Telegram'
}
