/** Tiered CRM reply alerts — soft chime (5m), buzzer (10m), aggressive (20m). */

import { isMessageSoundMuted } from './soundQuietHours.js'
import { getSharedAudioContext, unlockNotificationSound } from './notificationSound.js'
import {
  AGGRESSIVE_BEEP_INTERVAL_MS,
  BUZZER_BEEP_INTERVAL_MS,
  conversationAlertKey,
  getMaxReplyAlertLevel,
  isBuzzerAlertsEnabled,
  listAlertConversations,
} from './replyAlert.js'

let loopActive = false
let loopMode = null // 'buzzer' | 'aggressive'
let beepTimer = null
const softNotified = new Set()

function playSoftReplyChime(ctx) {
  const t0 = ctx.currentTime
  const master = ctx.createGain()
  master.gain.setValueAtTime(0.28, t0)
  master.gain.exponentialRampToValueAtTime(0.001, t0 + 0.55)
  master.connect(ctx.destination)

  const osc = ctx.createOscillator()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(523.25, t0)
  osc.frequency.exponentialRampToValueAtTime(392, t0 + 0.35)

  const g = ctx.createGain()
  g.gain.setValueAtTime(0.001, t0)
  g.gain.linearRampToValueAtTime(0.7, t0 + 0.04)
  g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.55)

  osc.connect(g)
  g.connect(master)
  osc.start(t0)
  osc.stop(t0 + 0.56)
}

function playBuzzerBeep(ctx, aggressive = false) {
  const t0 = ctx.currentTime
  const master = ctx.createGain()
  master.gain.setValueAtTime(aggressive ? 0.72 : 0.55, t0)
  master.gain.exponentialRampToValueAtTime(0.001, t0 + (aggressive ? 0.55 : 0.45))
  master.connect(ctx.destination)

  const osc = ctx.createOscillator()
  osc.type = 'square'
  const f1 = aggressive ? 1046 : 880
  const f2 = aggressive ? 784 : 660
  osc.frequency.setValueAtTime(f1, t0)
  osc.frequency.setValueAtTime(f2, t0 + 0.1)
  osc.frequency.setValueAtTime(f1, t0 + 0.2)
  if (aggressive) {
    osc.frequency.setValueAtTime(f2, t0 + 0.3)
    osc.frequency.setValueAtTime(f1, t0 + 0.4)
  }

  const g = ctx.createGain()
  g.gain.setValueAtTime(0.001, t0)
  g.gain.linearRampToValueAtTime(aggressive ? 0.95 : 0.85, t0 + 0.02)
  g.gain.setValueAtTime(aggressive ? 0.95 : 0.85, t0 + 0.32)
  g.gain.exponentialRampToValueAtTime(0.001, t0 + (aggressive ? 0.55 : 0.45))

  osc.connect(g)
  g.connect(master)
  osc.start(t0)
  osc.stop(t0 + (aggressive ? 0.56 : 0.46))

  if (aggressive) {
    const osc2 = ctx.createOscillator()
    osc2.type = 'sawtooth'
    osc2.frequency.setValueAtTime(220, t0)
    const g2 = ctx.createGain()
    g2.gain.setValueAtTime(0.12, t0)
    g2.gain.exponentialRampToValueAtTime(0.001, t0 + 0.4)
    osc2.connect(g2)
    g2.connect(master)
    osc2.start(t0)
    osc2.stop(t0 + 0.42)
  }
}

function stopLoop() {
  loopActive = false
  loopMode = null
  if (beepTimer != null) {
    clearTimeout(beepTimer)
    beepTimer = null
  }
}

function scheduleLoopBeep(ctx) {
  if (!loopActive || !loopMode) return
  try {
    playBuzzerBeep(ctx, loopMode === 'aggressive')
  } catch {
    /* ignore */
  }
  const delay = loopMode === 'aggressive' ? AGGRESSIVE_BEEP_INTERVAL_MS : BUZZER_BEEP_INTERVAL_MS
  beepTimer = window.setTimeout(() => scheduleLoopBeep(ctx), delay)
}

function startLoop(ctx, mode) {
  if (loopActive && loopMode === mode) return
  stopLoop()
  loopActive = true
  loopMode = mode
  scheduleLoopBeep(ctx)
}

function pruneSoftNotified(activeKeys) {
  for (const key of [...softNotified]) {
    if (!activeKeys.has(key)) softNotified.delete(key)
  }
}

function playSoftOnce(ctx) {
  try {
    playSoftReplyChime(ctx)
  } catch {
    /* ignore */
  }
}

/**
 * Drive tiered reply alerts from full inbox state.
 * @param {object} inboxState
 */
export function syncReplyAlerts(inboxState) {
  if (!isBuzzerAlertsEnabled() || isMessageSoundMuted()) {
    stopLoop()
    return
  }

  const items = listAlertConversations(inboxState)
  const activeKeys = new Set(items.map(i => conversationAlertKey(i.conv)))
  pruneSoftNotified(activeKeys)

  const ctx = getSharedAudioContext()
  if (!ctx) return

  const run = () => {
    for (const item of items) {
      if (item.level !== 'soft') continue
      const key = conversationAlertKey(item.conv)
      if (softNotified.has(key)) continue
      softNotified.add(key)
      playSoftOnce(ctx)
    }

    const maxLevel = getMaxReplyAlertLevel(inboxState)
    if (maxLevel === 'aggressive') {
      startLoop(ctx, 'aggressive')
    } else if (maxLevel === 'buzzer') {
      startLoop(ctx, 'buzzer')
    } else {
      stopLoop()
    }
  }

  if (ctx.state === 'suspended') {
    ctx.resume().then(run).catch(() => {})
  } else {
    run()
  }
}

/** @deprecated use syncReplyAlerts */
export function syncReplyBuzzer(delayedCount) {
  if (delayedCount > 0) {
    const ctx = getSharedAudioContext()
    if (ctx) startLoop(ctx, 'buzzer')
  } else {
    stopLoop()
  }
}

export function stopReplyBuzzerOnUnmount() {
  stopLoop()
}

export { unlockNotificationSound }
