import { useCallback, useEffect, useRef, useState } from 'react'
import { startVoiceCall, endVoiceCall } from '../utils/voiceCallApi.js'
import {
  isTerminalVoiceStatus,
  sessionStatusFromVoiceEvent,
  voiceChannelLabel,
} from './voiceCallEvents.js'

function buildOutgoingBase({ name, seed, session, status = 'ringing', error = null }) {
  return {
    name,
    seed,
    sessionId: session?.id || null,
    channelId: session?.call_mode || 'telegram',
    channelLabel: voiceChannelLabel(session?.call_mode || 'telegram'),
    status,
    muted: true,
    minimized: false,
    error,
    durationSec: Number(session?.duration_sec || 0),
    connectedAt: session?.connected_at || null,
  }
}

export function useTelegramVoiceCall({ selected, selectedConv, liveCallContact, onToast }) {
  const [outgoingCall, setOutgoingCall] = useState(null)
  const startingRef = useRef(false)
  const endingRef = useRef(false)
  const activeRef = useRef(null)

  useEffect(() => {
    activeRef.current = outgoingCall
  }, [outgoingCall])

  const applySessionUpdate = useCallback((event, session) => {
    const cur = activeRef.current
    if (!cur?.sessionId || !session?.id || session.id !== cur.sessionId) return
    const nextStatus = sessionStatusFromVoiceEvent(event, session)
    setOutgoingCall(prev => {
      if (!prev) return prev
      return {
        ...prev,
        status: nextStatus,
        durationSec: Number(session.duration_sec || prev.durationSec || 0),
        connectedAt: session.connected_at || prev.connectedAt,
        error: nextStatus === 'failed' ? (prev.error || 'Call failed') : null,
      }
    })
    if (isTerminalVoiceStatus(nextStatus)) {
      window.setTimeout(() => {
        setOutgoingCall(p => (p?.sessionId === session.id ? null : p))
      }, nextStatus === 'ended' ? 1200 : 400)
    }
  }, [])

  useEffect(() => {
    function onSession(e) {
      const d = e.detail || {}
      applySessionUpdate(d.event, d.session)
    }
    function onAnswered(e) {
      applySessionUpdate('telegram_answered', e.detail?.session)
    }
    function onActive(e) {
      applySessionUpdate('telegram_active', e.detail?.session)
    }
    function onEnded(e) {
      applySessionUpdate(e.detail?.event || 'telegram_ended', e.detail?.session)
    }
    function onFailed(e) {
      applySessionUpdate('telegram_failed', e.detail?.session)
    }
    window.addEventListener('voice-call-session', onSession)
    window.addEventListener('voice-call-telegram-answered', onAnswered)
    window.addEventListener('voice-call-telegram-active', onActive)
    window.addEventListener('voice-call-telegram-ended', onEnded)
    window.addEventListener('voice-call-telegram-failed', onFailed)
    return () => {
      window.removeEventListener('voice-call-session', onSession)
      window.removeEventListener('voice-call-telegram-answered', onAnswered)
      window.removeEventListener('voice-call-telegram-active', onActive)
      window.removeEventListener('voice-call-telegram-ended', onEnded)
      window.removeEventListener('voice-call-telegram-failed', onFailed)
    }
  }, [applySessionUpdate])

  useEffect(() => {
    if (!selected && outgoingCall) {
      setOutgoingCall(null)
    }
  }, [selected, outgoingCall])

  const endOutgoingCall = useCallback(async (status = 'declined') => {
    const cur = activeRef.current
    if (!cur?.sessionId) {
      setOutgoingCall(null)
      return
    }
    if (endingRef.current) return
    endingRef.current = true
    try {
      await endVoiceCall(cur.sessionId, { status })
    } catch {
      /* still clear UI */
    } finally {
      endingRef.current = false
      setOutgoingCall(null)
    }
  }, [])

  const startOutgoingCall = useCallback(async () => {
    if (!selected || !liveCallContact || startingRef.current) return false
    if (activeRef.current?.sessionId && !isTerminalVoiceStatus(activeRef.current.status)) {
      onToast?.('Already on a call — end it first')
      return false
    }
    startingRef.current = true
    const name = liveCallContact.name
      || selectedConv?.name
      || selectedConv?.username
      || String(selected.user_id)
    const seed = `${selected.slot}-${selected.user_id}`

    try {
      const data = await startVoiceCall(selected.slot, selected.user_id, {
        callMode: 'telegram',
        sendJoinDm: false,
      })
      const session = data.session || {}
      const base = buildOutgoingBase({ name, seed, session, status: 'ringing' })
      setOutgoingCall(base)
      onToast?.('Calling — answer on your business Telegram app')
      return true
    } catch (e) {
      const msg = String(e.message || e)
      setOutgoingCall({
        name,
        seed,
        sessionId: null,
        channelLabel: voiceChannelLabel('telegram'),
        status: 'failed',
        muted: true,
        minimized: false,
        error: msg,
        durationSec: 0,
      })
      onToast?.(msg)
      return false
    } finally {
      startingRef.current = false
    }
  }, [selected, liveCallContact, selectedConv, onToast])

  const startWithMode = useCallback(async (callMode, { sendJoinDm = false } = {}) => {
    if (!selected || startingRef.current) return
    const name = liveCallContact?.name
      || selectedConv?.name
      || String(selected.user_id)
    const seed = `${selected.slot}-${selected.user_id}`
    startingRef.current = true
    try {
      const data = await startVoiceCall(selected.slot, selected.user_id, {
        callMode,
        sendJoinDm,
      })
      const session = data.session || {}
      setOutgoingCall(buildOutgoingBase({ name, seed, session, status: 'ringing' }))
      if (callMode === 'hybrid' && data.join_url) {
        window.open(data.join_url, '_blank', 'noopener,noreferrer')
      }
    } catch (e) {
      setOutgoingCall({
        name,
        seed,
        sessionId: null,
        status: 'failed',
        error: String(e.message || e),
        channelLabel: voiceChannelLabel(callMode),
        muted: true,
        minimized: false,
        durationSec: 0,
      })
    } finally {
      startingRef.current = false
    }
  }, [selected, liveCallContact, selectedConv])

  return {
    outgoingCall,
    setOutgoingCall,
    startOutgoingCall,
    startWithMode,
    endOutgoingCall,
  }
}
