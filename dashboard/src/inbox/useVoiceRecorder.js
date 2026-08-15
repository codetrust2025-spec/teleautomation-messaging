import { useCallback, useEffect, useRef, useState } from 'react'

const MIN_RECORD_MS = 400

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
]

function pickRecorderMime() {
  if (typeof MediaRecorder === 'undefined') return ''
  for (const mime of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime
  }
  return ''
}

export function isVoiceRecordingSupported() {
  return typeof navigator !== 'undefined'
    && !!navigator.mediaDevices?.getUserMedia
    && typeof MediaRecorder !== 'undefined'
    && !!pickRecorderMime()
}

export function formatVoiceRecordSeconds(total) {
  const s = Math.max(0, Number(total) || 0)
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

export function useVoiceRecorder() {
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const chunksRef = useRef([])
  const startMsRef = useRef(0)
  const timerRef = useRef(null)

  const cleanupStream = useCallback(() => {
    const stream = streamRef.current
    if (!stream) return
    stream.getTracks().forEach(track => track.stop())
    streamRef.current = null
  }, [])

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (recorderRef.current?.state === 'recording') {
      try {
        recorderRef.current.stop()
      } catch {
        /* ignore */
      }
    }
    cleanupStream()
  }, [cleanupStream])

  const cancel = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setRecording(false)
    setSeconds(0)
    chunksRef.current = []
    const recorder = recorderRef.current
    recorderRef.current = null
    if (recorder?.state === 'recording') {
      try {
        recorder.stop()
      } catch {
        /* ignore */
      }
    }
    cleanupStream()
  }, [cleanupStream])

  const start = useCallback(async () => {
    setError('')
    if (recording) return false
    const mime = pickRecorderMime()
    if (!mime) {
      setError('Voice recording is not supported in this browser')
      return false
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
      streamRef.current = stream
      const recorder = new MediaRecorder(stream, { mimeType: mime })
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data?.size > 0) chunksRef.current.push(event.data)
      }
      recorderRef.current = recorder
      recorder.start(200)
      startMsRef.current = Date.now()
      setSeconds(0)
      setRecording(true)
      timerRef.current = window.setInterval(() => {
        setSeconds(prev => prev + 1)
      }, 1000)
      return true
    } catch (err) {
      cleanupStream()
      const denied = err?.name === 'NotAllowedError' || err?.name === 'PermissionDeniedError'
      setError(denied ? 'Microphone permission denied' : (err?.message || 'Could not start recording'))
      return false
    }
  }, [recording, cleanupStream])

  const stop = useCallback(() => new Promise((resolve) => {
    if (!recording || !recorderRef.current) {
      resolve(null)
      return
    }
    const elapsed = Date.now() - startMsRef.current
    const recorder = recorderRef.current
    recorderRef.current = null
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    setRecording(false)
    setSeconds(0)

    recorder.onstop = () => {
      cleanupStream()
      if (elapsed < MIN_RECORD_MS || !chunksRef.current.length) {
        chunksRef.current = []
        resolve(null)
        return
      }
      const mime = recorder.mimeType || pickRecorderMime() || 'audio/webm'
      const blob = new Blob(chunksRef.current, { type: mime })
      chunksRef.current = []
      const ext = mime.includes('ogg') ? 'ogg' : 'webm'
      resolve(new File([blob], `voice-${Date.now()}.${ext}`, { type: mime }))
    }

    try {
      recorder.stop()
    } catch {
      cleanupStream()
      resolve(null)
    }
  }), [recording, cleanupStream])

  return {
    recording,
    seconds,
    error,
    start,
    stop,
    cancel,
    supported: isVoiceRecordingSupported(),
  }
}
