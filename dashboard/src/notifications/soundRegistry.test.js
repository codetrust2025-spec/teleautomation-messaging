import { beforeEach, describe, expect, it } from 'vitest'
import { NOTIFICATION_IDS, NOTIFICATION_SOUNDS } from './soundRegistry.js'
import { installRecordingAudioStub } from './audioTestStub.js'

describe('Marketing notification sound catalogue', () => {
  it('contains only the seven Marketing notifications', () => {
    expect(NOTIFICATION_IDS).toEqual([
      'dm', 'unread_ghost', 'incoming_call', 'call_reminder', 'sla_5', 'sla_10', 'sla_20',
    ])
    expect(Object.keys(NOTIFICATION_SOUNDS).sort()).toEqual([...NOTIFICATION_IDS].sort())
  })

  it('gives every notification its own sound function and dedupe rule', () => {
    const functions = NOTIFICATION_IDS.map((id) => NOTIFICATION_SOUNDS[id].play)
    expect(new Set(functions).size).toBe(NOTIFICATION_IDS.length)
    for (const id of NOTIFICATION_IDS) expect(NOTIFICATION_SOUNDS[id].dedupe).toBeTruthy()
  })
})

describe('Marketing notification sound signatures', () => {
  let audio
  beforeEach(() => { audio = installRecordingAudioStub() })

  it('keeps the 10-minute pulse distinct from the 20-minute siren', () => {
    NOTIFICATION_SOUNDS.sla_10.play()
    const pulse = [...new Set(audio.record.oscillatorTypes)]
    NOTIFICATION_SOUNDS.sla_10.stop()
    audio.reset()
    NOTIFICATION_SOUNDS.sla_20.play()
    const siren = [...new Set(audio.record.oscillatorTypes)]
    NOTIFICATION_SOUNDS.sla_20.stop()
    expect(pulse).toEqual(['square'])
    expect(siren).toEqual(['sawtooth'])
  })
})
