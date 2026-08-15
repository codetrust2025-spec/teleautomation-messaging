import React, { memo, useCallback, useMemo, useState } from 'react'
import { MessageBubble } from './MessageBubble.jsx'
import { MessageActionMenu } from './MessageActionMenu.jsx'
import { buildMessageTimeline } from './inboxUiUtils.js'
import {
  canDeleteOutboundMessage,
  canEditOutboundMessage,
} from '../utils/inboxMessageUtils.js'
import { copyToClipboard } from '../utils/copyToClipboard.js'
import { isMessagePinned, toggleMessagePin } from '../utils/inboxPinned.js'

function TimelineDate({ label }) {
  return (
    <div className="tg-date-divider" role="separator">
      <span className="tg-date-pill">{label}</span>
    </div>
  )
}

function MessageTimelineInner({
  messages,
  loadingMessages,
  messagesEndRef,
  chatSlot = null,
  chatUserId = null,
  selectedConv = null,
  whatsappEnabled = false,
  blocked = false,
  onEditMessage,
  onDeleteMessage,
  onReplyToMessage,
  onForwardMessage,
  onQuickReaction,
  selectMode = false,
  selectedMessageIds,
  onToggleSelect,
  onEnterSelectMode,
  pinVersion = 0,
}) {
  const [actionMenu, setActionMenu] = useState(null)
  const [forceEditMessageId, setForceEditMessageId] = useState(null)
  const [pinTick, setPinTick] = useState(0)

  const timeline = useMemo(() => buildMessageTimeline(messages || []), [messages])
  const selectedSet = useMemo(
    () => (selectedMessageIds instanceof Set ? selectedMessageIds : new Set(selectedMessageIds || [])),
    [selectedMessageIds],
  )

  const closeMenu = useCallback(() => setActionMenu(null), [])

  const openMenu = useCallback((message, x, y) => {
    setActionMenu({ message, x, y })
  }, [])

  const menuMessage = actionMenu?.message
  const menuOut = menuMessage?.direction === 'out'
  const menuCanCopy = Boolean((menuMessage?.text || '').trim())
  const menuCanEdit = menuMessage
    && canEditOutboundMessage(menuMessage, { blocked })
    && typeof onEditMessage === 'function'
  const menuCanDelete = menuMessage
    && canDeleteOutboundMessage(menuMessage, { blocked })
    && typeof onDeleteMessage === 'function'
  const menuPinned = menuMessage && chatSlot && chatUserId != null
    ? isMessagePinned(chatSlot, chatUserId, menuMessage.id)
    : false

  const handleCopy = useCallback(async () => {
    const text = (menuMessage?.text || '').trim()
    if (!text) return
    await copyToClipboard(text)
  }, [menuMessage?.text])

  const handlePin = useCallback(() => {
    if (!menuMessage || !chatSlot || chatUserId == null) return
    toggleMessagePin(chatSlot, chatUserId, menuMessage.id)
    setPinTick(t => t + 1)
  }, [menuMessage, chatSlot, chatUserId])

  if (loadingMessages) {
    return <div className="empty-state">Loading…</div>
  }
  if (!timeline.length) {
    return <div className="empty-state">No messages stored yet.</div>
  }

  void pinVersion
  void pinTick

  return (
    <>
      {timeline.map(it => (
        it.kind === 'date'
          ? <TimelineDate key={it.id} label={it.label} />
          : (
            <MessageBubble
              key={it.id}
              message={it.message}
              chatSlot={chatSlot}
              chatUserId={chatUserId}
              blocked={blocked}
              onEditMessage={onEditMessage}
              onDeleteMessage={onDeleteMessage}
              onOpenActionMenu={openMenu}
              selectMode={selectMode}
              selected={selectedSet.has(it.message.id)}
              onToggleSelect={onToggleSelect}
              isPinned={chatSlot && chatUserId != null
                ? isMessagePinned(chatSlot, chatUserId, it.message.id)
                : false}
              forceEditMessageId={forceEditMessageId}
              onForceEditConsumed={() => setForceEditMessageId(null)}
              selectedConv={selectedConv}
              whatsappEnabled={whatsappEnabled}
            />
          )
      ))}
      <div className="inbox-messages-anchor" ref={messagesEndRef} aria-hidden />
      <MessageActionMenu
        open={Boolean(actionMenu)}
        x={actionMenu?.x ?? 0}
        y={actionMenu?.y ?? 0}
        out={menuOut}
        showReactions={!menuOut && !blocked}
        canReply={!blocked && typeof onReplyToMessage === 'function'}
        canCopy={menuCanCopy}
        canEdit={menuCanEdit}
        canDelete={menuCanDelete}
        canPin={Boolean(chatSlot && chatUserId != null)}
        isPinned={menuPinned}
        onClose={closeMenu}
        onReply={() => onReplyToMessage?.(menuMessage)}
        onCopy={handleCopy}
        onEdit={() => {
          if (menuMessage) setForceEditMessageId(menuMessage.id)
        }}
        onDelete={() => onDeleteMessage?.(menuMessage?.id)}
        onPin={handlePin}
        onForward={() => onForwardMessage?.(menuMessage)}
        onSelect={() => onEnterSelectMode?.(menuMessage?.id)}
        onReaction={emoji => onQuickReaction?.(emoji, menuMessage)}
      />
    </>
  )
}

export const MessageTimeline = memo(MessageTimelineInner)
