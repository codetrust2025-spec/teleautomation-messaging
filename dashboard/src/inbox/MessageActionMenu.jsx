import React, { memo, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

const REACTIONS = ['❤️', '👍', '👎', '🔥', '🥰', '👏', '😁']

function MenuItem({ icon, label, danger, disabled, onClick }) {
  return (
    <button
      type="button"
      role="menuitem"
      className={`tg-msg-menu-item${danger ? ' tg-msg-menu-item--danger' : ''}`}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="tg-msg-menu-icon" aria-hidden>{icon}</span>
      <span className="tg-msg-menu-label">{label}</span>
    </button>
  )
}

function MessageActionMenuInner({
  open,
  x,
  y,
  out,
  showReactions,
  canReply,
  canCopy,
  canEdit,
  canDelete,
  canPin,
  isPinned,
  onClose,
  onReply,
  onCopy,
  onEdit,
  onDelete,
  onPin,
  onForward,
  onSelect,
  onReaction,
}) {
  const layerRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (ev) => {
      if (layerRef.current?.contains(ev.target)) return
      onClose?.()
    }
    const onKey = (ev) => {
      if (ev.key === 'Escape') onClose?.()
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  useEffect(() => {
    if (!open || !layerRef.current) return
    const el = layerRef.current
    const rect = el.getBoundingClientRect()
    const pad = 8
    let left = x
    let top = y
    if (left + rect.width > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - rect.width - pad)
    }
    if (top + rect.height > window.innerHeight - pad) {
      top = Math.max(pad, y - rect.height - 4)
    }
    el.style.left = `${left}px`
    el.style.top = `${top}px`
  }, [open, x, y])

  if (!open) return null

  const node = (
    <div
      ref={layerRef}
      className="tg-msg-menu-layer"
      role="presentation"
      style={{ left: x, top: y }}
    >
      {showReactions && (
        <div className={`tg-msg-reactions${out ? ' tg-msg-reactions--out' : ''}`}>
          {REACTIONS.map(emoji => (
            <button
              key={emoji}
              type="button"
              className="tg-msg-reaction-btn"
              title={`React ${emoji}`}
              onClick={() => {
                onReaction?.(emoji)
                onClose?.()
              }}
            >
              {emoji}
            </button>
          ))}
        </div>
      )}
      <div
        className={`tg-msg-menu${out ? ' tg-msg-menu--out' : ''}`}
        role="menu"
      >
        {canReply && (
          <MenuItem icon="↩" label="Reply" onClick={() => { onReply?.(); onClose?.() }} />
        )}
        {canCopy && (
          <MenuItem icon="⧉" label="Copy" onClick={() => { onCopy?.(); onClose?.() }} />
        )}
        {canEdit && (
          <MenuItem icon="✎" label="Edit" onClick={() => { onEdit?.(); onClose?.() }} />
        )}
        {canPin && (
          <MenuItem
            icon="📌"
            label={isPinned ? 'Unpin' : 'Pin'}
            onClick={() => { onPin?.(); onClose?.() }}
          />
        )}
        {canCopy && (
          <MenuItem
            icon="↪"
            label="Forward"
            onClick={() => { onForward?.(); onClose?.() }}
          />
        )}
        {canDelete && (
          <>
            <div className="tg-msg-menu-sep" role="separator" />
            <MenuItem
              icon="🗑"
              label="Delete"
              danger
              onClick={() => { onDelete?.(); onClose?.() }}
            />
          </>
        )}
        <div className="tg-msg-menu-sep" role="separator" />
        <MenuItem icon="☑" label="Select" onClick={() => { onSelect?.(); onClose?.() }} />
      </div>
    </div>
  )

  return createPortal(node, document.body)
}

export const MessageActionMenu = memo(MessageActionMenuInner)
