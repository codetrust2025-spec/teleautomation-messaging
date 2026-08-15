import React, { memo, useRef, useEffect } from 'react'
import { ReplyQuoteBar } from './ReplyQuoteBar.jsx'
import { formatVoiceRecordSeconds, useVoiceRecorder } from './useVoiceRecorder.js'

const ATTACH_ACCEPT = [
  'image/*',
  'video/*',
  'audio/*',
  '.pdf',
  '.doc',
  '.docx',
  '.txt',
  '.ogg',
  '.opus',
].join(',')

function ChatComposerInner({
  replyText,
  onReplyChange,
  onSend,
  onSendMedia,
  sending,
  sendingMedia = false,
  blocked,
  error,
  replyToMessage = null,
  onClearReply,
  whatsappEnabled = false,
  whatsappConfigured = false,
  selectedConv = null,
  replyChannel = 'telegram',
  onReplyChannelChange,
}) {
  const textareaRef = useRef(null)
  const fileRef = useRef(null)
  const micActiveRef = useRef(false)
  const voice = useVoiceRecorder()
  const hasText = Boolean(replyText.trim())
  const busy = sending || sendingMedia || voice.recording
  const canSendMedia = typeof onSendMedia === 'function'
  const voiceError = voice.error
  const composeError = error || voiceError

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const max = 120
    el.style.height = `${Math.min(max, Math.max(20, el.scrollHeight))}px`
  }, [replyText])

  useEffect(() => {
    if (replyToMessage && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [replyToMessage])

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || blocked || busy || !canSendMedia) return
    onSendMedia(file)
  }

  async function finishVoiceRecording() {
    if (!micActiveRef.current && !voice.recording) return
    micActiveRef.current = false
    if (!voice.recording) return
    const file = await voice.stop()
    if (file && canSendMedia) onSendMedia(file)
  }

  async function handleMicPointerDown(e) {
    if (hasText || blocked || busy || !canSendMedia || !voice.supported) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    const started = await voice.start()
    micActiveRef.current = started
  }

  function handleMicPointerUp(e) {
    if (!hasText) {
      e.preventDefault()
      finishVoiceRecording()
    }
  }

  function handleMicPointerCancel() {
    micActiveRef.current = false
    if (voice.recording) voice.cancel()
  }

  const micEnabled = !hasText && canSendMedia && voice.supported && !blocked && !busy

  const canWaReply = Boolean(
    selectedConv?.phone_e164 || selectedConv?.whatsapp_linked,
  )

  return (
    <footer className={`inbox-compose reply-box crm-compose tg-composer${voice.recording ? ' tg-composer--recording' : ''}`}>
      {composeError && <p className="inbox-error inbox-error--compose" role="alert">{composeError}</p>}

      {whatsappEnabled && !blocked && (
        <div className="crm-channel-toggle" role="group" aria-label="Reply channel">
          <span className="crm-channel-toggle-label">Send via</span>
          <button
            type="button"
            className={`crm-channel-toggle-btn${replyChannel === 'telegram' ? ' crm-channel-toggle-btn--active' : ''}`}
            onClick={() => onReplyChannelChange?.('telegram')}
          >
            Telegram
          </button>
          <button
            type="button"
            className={`crm-channel-toggle-btn${replyChannel === 'whatsapp' ? ' crm-channel-toggle-btn--active' : ''}`}
            onClick={() => onReplyChannelChange?.('whatsapp')}
            disabled={!canWaReply || !whatsappConfigured}
            title={whatsappConfigured
              ? (canWaReply ? 'Reply on WhatsApp' : 'Link a phone number first (Lead details panel)')
              : 'WhatsApp API not configured on server'}
          >
            WhatsApp
          </button>
        </div>
      )}

      <ReplyQuoteBar message={replyToMessage} onClear={onClearReply} />

      {voice.recording && (
        <div className="tg-composer-voice-recording" role="status" aria-live="polite">
          <span className="tg-composer-voice-dot" aria-hidden />
          <span>{formatVoiceRecordSeconds(voice.seconds)} · Release to send</span>
        </div>
      )}

      <div className="tg-composer-row">
        <button
          type="button"
          className="tg-composer-side-btn tg-composer-attach"
          aria-label="Attach photo or file"
          title="Attach photo, video, voice, or document (max 25 MB)"
          disabled={blocked || busy || !canSendMedia}
          onClick={() => fileRef.current?.click()}
        >
          <span className="tg-icon-attach" aria-hidden />
        </button>
        <input
          ref={fileRef}
          type="file"
          className="sr-only"
          accept={ATTACH_ACCEPT}
          onChange={handleFileChange}
          tabIndex={-1}
        />
        <div className="tg-composer-pill">
          <textarea
            ref={textareaRef}
            className="tg-composer-input"
            rows={1}
            placeholder={
              blocked
                ? 'Unblock to reply…'
                : voice.recording
                  ? 'Recording voice…'
                  : 'Message'
            }
            value={replyText}
            onChange={e => onReplyChange(e.target.value)}
            disabled={blocked || busy}
            onKeyDown={e => {
              if (e.key === 'Escape' && replyToMessage) {
                e.preventDefault()
                onClearReply?.()
              } else if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (!busy && !blocked && hasText) onSend()
              }
            }}
          />
        </div>
        <button
          type="button"
          className={[
            'tg-composer-action',
            hasText ? 'tg-composer-action--send' : '',
            voice.recording ? 'tg-composer-action--recording' : '',
          ].filter(Boolean).join(' ')}
          onClick={hasText ? onSend : undefined}
          onPointerDown={!hasText ? handleMicPointerDown : undefined}
          onPointerUp={!hasText ? handleMicPointerUp : undefined}
          onPointerCancel={!hasText ? handleMicPointerCancel : undefined}
          disabled={
            blocked
            || (voice.recording ? false : (sending || sendingMedia))
            || (hasText ? !hasText : !micEnabled && !voice.recording)
          }
          aria-label={
            hasText
              ? 'Send message'
              : voice.recording
                ? 'Recording voice — release to send'
                : voice.supported
                  ? 'Hold to record voice message'
                  : 'Type a message or attach a voice file'
          }
          title={
            hasText
              ? 'Send'
              : voice.supported
                ? 'Hold to record voice'
                : 'Use attach for voice files'
          }
        >
          {sending || sendingMedia ? (
            <span className="tg-composer-action-spinner">…</span>
          ) : hasText ? (
            <span className="tg-composer-action-send" aria-hidden />
          ) : (
            <span className="tg-composer-action-mic" aria-hidden />
          )}
        </button>
      </div>
    </footer>
  )
}

export const ChatComposer = memo(ChatComposerInner)
