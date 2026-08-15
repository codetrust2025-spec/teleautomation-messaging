import React, { memo, useCallback, useEffect, useRef, useState } from 'react'
import {
  canDeleteOutboundMessage,
  canEditOutboundMessage,
  formatInboxTime,
} from '../utils/inboxMessageUtils.js'
import { formatIstDateTime } from '../utils/istTime.js'
import { MessageStatus } from '../components/crm/MessageStatus.jsx'
import { InlineLoader } from '../Loader.jsx'
import { API } from '../config.js'
import {
  documentFileLabel,
  inferMediaKind,
  inboxMediaSrc,
  INBOX_MEDIA_PLACEHOLDERS,
  isFilenameOnlyCaption,
  messageChannel,
} from './inboxUiUtils.js'
import { InboxMediaAttachment } from './InboxMediaAttachment.jsx'
import { MessageBubbleText } from './MessageBubbleText.jsx'

const PLAYABLE_MEDIA = new Set(['photo', 'video', 'voice', 'audio', 'document', 'sticker', 'media'])

const MEDIA_LABELS = {
  photo: 'Photo',
  video: 'Video',
  audio: 'Audio',
  voice: 'Voice message',
  document: 'Document',
  sticker: 'Sticker',
  media: 'Media',
}

const PLACEHOLDER_TEXTS = INBOX_MEDIA_PLACEHOLDERS

function outboundSenderLabel(m) {
  if (m.direction !== 'out') return null
  const name = (m.sender_name || '').trim()
  if (name) return name
  const sb = String(m.sent_by || '').toLowerCase()
  if (sb === 'ai' && (m.ai_stage || m.ai_confidence != null)) return 'AI'
  if (sb === 'ai' && !m.ai_stage && m.ai_confidence == null) {
    return name && name !== 'AI' ? name : 'Telegram'
  }
  if (m.ai && sb === 'ai') return 'AI'
  if (sb === 'native' || sb === 'telegram') return name || 'Telegram'
  if (sb === 'ai_approved') return name || 'Operator'
  if (sb === 'manual' || sb === 'operator') return name || 'Operator'
  if (name) return name
  return null
}

function MessageBubbleInner({
  message: m,
  chatSlot = null,
  chatUserId = null,
  blocked = false,
  onEditMessage,
  onDeleteMessage,
  onOpenActionMenu,
  selectMode = false,
  selected = false,
  onToggleSelect,
  isPinned = false,
  forceEditMessageId = null,
  onForceEditConsumed,
  selectedConv = null,
  whatsappEnabled = false,
}) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [editError, setEditError] = useState('')
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef(null)
  const bubbleRef = useRef(null)

  const canEdit = canEditOutboundMessage(m, { blocked }) && typeof onEditMessage === 'function'
  const canDelete = canDeleteOutboundMessage(m, { blocked }) && typeof onDeleteMessage === 'function'

  const openMenu = useCallback((clientX, clientY) => {
    if (editing || selectMode || typeof onOpenActionMenu !== 'function') return
    onOpenActionMenu(m, clientX, clientY)
  }, [editing, m, onOpenActionMenu, selectMode])

  const onContextMenu = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    openMenu(e.clientX, e.clientY)
  }, [openMenu])

  const onBubbleClick = useCallback((e) => {
    if (selectMode) {
      e.stopPropagation()
      onToggleSelect?.(m.id)
      return
    }
    if (editing) return
    if (e.target.closest('a, button, textarea, video, audio, img, .inbox-bubble-media-wrap')) return
    openMenu(e.clientX, e.clientY)
  }, [editing, m.id, onToggleSelect, openMenu, selectMode])

  const startEdit = useCallback(() => {
    setEditText((m.text || '').trim())
    setEditError('')
    setEditing(true)
  }, [m.text])

  const cancelEdit = useCallback(() => {
    if (saving) return
    setEditing(false)
    setEditText('')
    setEditError('')
  }, [saving])

  const saveEdit = useCallback(async () => {
    const next = editText.trim()
    if (!next) {
      setEditError('Message cannot be empty')
      return
    }
    if (next === (m.text || '').trim()) {
      cancelEdit()
      return
    }
    setSaving(true)
    setEditError('')
    const result = await onEditMessage(m.id, next)
    setSaving(false)
    if (result?.ok) {
      setEditing(false)
      setEditText('')
    } else if (result?.error) {
      setEditError(result.error)
    }
  }, [editText, m.id, m.text, onEditMessage, cancelEdit])

  useEffect(() => {
    if (!editing || !textareaRef.current) return
    const el = textareaRef.current
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
  }, [editing])

  useEffect(() => {
    if (!editing) return undefined
    const onKey = (ev) => {
      if (ev.key === 'Escape') cancelEdit()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [editing, cancelEdit])

  useEffect(() => {
    if (forceEditMessageId == null || Number(forceEditMessageId) !== Number(m.id)) return
    if (!canEdit || editing) return
    startEdit()
    onForceEditConsumed?.()
  }, [forceEditMessageId, m.id, canEdit, editing, startEdit, onForceEditConsumed])

  if (m.direction === 'system') {
    return (
      <div className="inbox-system-message tg-date-pill" role="status">
        {m.text}
      </div>
    )
  }

  const out = m.direction === 'out'
  const senderLabel = out ? outboundSenderLabel(m) : null
  const mediaKind = inferMediaKind(m)
  const slot = m.account_id || chatSlot
  const userId = m.chat_id ?? chatUserId
  const canPlayMedia = PLAYABLE_MEDIA.has(mediaKind)
    && slot && userId != null && m.id != null
  const showCaption = Boolean(
    m.text
    && !PLACEHOLDER_TEXTS.has(String(m.text).trim().toLowerCase())
    && !(mediaKind === 'document' && isFilenameOnlyCaption(m)),
  )
  const editedAt = m.edited_at || (m.edited ? m.timestamp : null)
  const timeLabel = formatInboxTime(m.timestamp)

  return (
    <div
      className={`tg-bubble-wrap tg-bubble-wrap--${out ? 'out' : 'in'}${selectMode ? ' tg-bubble-wrap--select' : ''}${selected ? ' tg-bubble-wrap--selected' : ''}`}
    >
      {selectMode && (
        <label className="tg-bubble-select-check">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect?.(m.id)}
            aria-label="Select message"
          />
        </label>
      )}
      <div
        ref={bubbleRef}
        role="button"
        tabIndex={selectMode ? 0 : -1}
        className={`inbox-bubble tg-bubble inbox-bubble--${out ? 'out' : 'in'} tg-bubble--${out ? 'out' : 'in'}${m.status === 'failed' ? ' inbox-bubble--failed' : ''}${m.status === 'sending' ? ' inbox-bubble--sending' : ''}${editing ? ' inbox-bubble--editing' : ''}${mediaKind ? ` inbox-bubble--${mediaKind}` : ''}${isPinned ? ' tg-bubble--pinned' : ''}`}
        onContextMenu={onContextMenu}
        onClick={onBubbleClick}
        onKeyDown={e => {
          if (selectMode && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            onToggleSelect?.(m.id)
          }
        }}
      >
        {isPinned && !editing && (
          <span className="tg-bubble-pin-badge" title="Pinned" aria-hidden>📌</span>
        )}
        {editing ? (
          <div className="inbox-bubble-edit">
            <textarea
              ref={textareaRef}
              className="input input--textarea inbox-bubble-edit-textarea"
              rows={3}
              value={editText}
              onChange={e => setEditText(e.target.value)}
              disabled={saving}
              onClick={e => e.stopPropagation()}
              onKeyDown={e => {
                if (e.key === 'Escape') {
                  e.preventDefault()
                  cancelEdit()
                } else if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  if (!saving && editText.trim()) saveEdit()
                }
              }}
            />
            {editError && (
              <div className="inbox-bubble-edit-error" role="alert">{editError}</div>
            )}
            <div className="inbox-bubble-edit-footer">
              <span className="inbox-bubble-edit-hint">
                {saving
                  ? <InlineLoader label="Saving…" size={12} />
                  : <>Enter to save · Shift+Enter for new line · Esc to cancel</>}
              </span>
              <button
                type="button"
                className="btn btn--ghost btn--sm inbox-bubble-edit-cancel"
                onClick={e => { e.stopPropagation(); cancelEdit() }}
                disabled={saving}
                aria-label="Cancel edit"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            {canPlayMedia && (
              <InboxMediaAttachment
                slot={slot}
                userId={userId}
                messageId={m.id}
                mediaKind={mediaKind}
                mediaSrc={inboxMediaSrc(API, slot, userId, m.id, messageChannel(m))}
                fileName={mediaKind === 'document' ? documentFileLabel(m) : undefined}
                alt={showCaption ? String(m.text).slice(0, 80) : MEDIA_LABELS[mediaKind] || 'Media'}
              />
            )}
            {mediaKind && !canPlayMedia && (
              <div className={`tg-media-card tg-media-card--${mediaKind}`} aria-label={MEDIA_LABELS[mediaKind]}>
                <span className="tg-media-card-icon" aria-hidden>
                  {mediaKind === 'photo' ? '🖼'
                    : mediaKind === 'video' ? '▶'
                      : mediaKind === 'voice' ? '🎤'
                        : mediaKind === 'audio' ? '🔊'
                          : mediaKind === 'document' ? '📄'
                            : mediaKind === 'sticker' ? '🎭'
                              : '📎'}
                </span>
                <span className="tg-media-card-label">{MEDIA_LABELS[mediaKind]}</span>
              </div>
            )}
            {showCaption && (
              <MessageBubbleText
                text={m.text}
                className={mediaKind ? 'inbox-bubble-image-caption' : ''}
              />
            )}
          </>
        )}

        <div className={`inbox-bubble-meta tg-bubble-meta${out ? ' inbox-bubble-meta--out' : ''}`}>
          {messageChannel(m) === 'whatsapp' && (
            <span className="inbox-channel-badge inbox-channel-badge--wa" title="WhatsApp">WA</span>
          )}
          {messageChannel(m) === 'telegram' && whatsappEnabled
            && ((selectedConv?.channels?.length > 1) || selectedConv?.whatsapp_linked) && (
            <span className="inbox-channel-badge inbox-channel-badge--tg" title="Telegram">TG</span>
          )}
          {senderLabel && !editing && (
            <span
              className={`inbox-bubble-sender-badge${senderLabel === 'AI' ? ' inbox-bubble-ai-badge' : ' inbox-bubble-human-badge'}`}
              title={senderLabel === 'AI' ? 'Sent by Karthik (AI auto-reply)' : `Sent by ${senderLabel}`}
            >
              {senderLabel}
            </span>
          )}
          {!editing && editedAt && (
            <span
              className="inbox-bubble-edited"
              title={`Edited ${formatIstDateTime(editedAt)}`}
            >
              edited
            </span>
          )}
          <time>{timeLabel}</time>
          <MessageStatus
            direction={m.direction}
            status={m.status || (m.direction === 'out' ? 'delivered' : 'received')}
          />
        </div>
      </div>
    </div>
  )
}

export const MessageBubble = memo(MessageBubbleInner)
