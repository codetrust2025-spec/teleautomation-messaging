import React, { memo, useEffect, useRef, useState } from 'react'
import { inboxAccountOwnerName } from '../utils/accountUi.js'
import { useCompactLayout } from '../utils/useCompactLayout.js'
import { avatarHue, displayInitials } from './inboxUiUtils.js'
import { formatWaitingLabel } from '../utils/leadUx.js'
import { InboxDemoTools } from './InboxDemoTools.jsx'

function ChatHeaderInner({
  selected,
  selectedConv,
  accountInfo = {},
  onBack,
  onBackToDashboard,
  onOpenDetails,
  onCallNow,
  onScheduleCall,
  onMarkSpam,
  onKarthikScanSpam,
  onMarkHandled,
  onRefreshChat,
  onDeleteChat,
  onExportChat,
  onOpenMarketingMessage,
  lead = null,
  onDemoToolsSent,
  exportingChat = false,
  refreshingChat,
  crmSaving,
  blocked,
  replyAlertLevel,
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)
  const compact = useCompactLayout()
  const name = selectedConv?.name || selectedConv?.username || String(selected?.user_id || '')
  const hue = avatarHue(`${selected?.slot}-${selected?.user_id}`)
  const waiting = formatWaitingLabel(selectedConv)
  const ownerName = inboxAccountOwnerName(selected?.slot, accountInfo)
  const statusParts = [waiting, ownerName].filter(Boolean)
  const statusLine = statusParts.join(' · ')

  useEffect(() => {
    if (!menuOpen) return undefined
    const close = e => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  return (
    <header className="inbox-chat-header tg-chat-header">
      <button
        type="button"
        className="inbox-chat-back-btn tg-chat-back"
        onClick={onBack}
        aria-label="Back to conversations"
      >
        ←
      </button>
      <button
        type="button"
        className="tg-chat-header-tap"
        onClick={onOpenDetails}
        aria-label="Open lead details"
      >
        <span
          className="tg-chat-header-avatar"
          style={{ '--tg-avatar-hue': hue }}
          aria-hidden
        >
          {displayInitials(name)}
        </span>
        <span className="tg-chat-header-text">
          <strong className="tg-chat-header-name">{name}</strong>
          <span className="tg-chat-header-status">{statusLine}</span>
        </span>
      </button>
      <div className="tg-chat-header-actions" ref={menuRef}>
        {!compact && !blocked && typeof onCallNow === 'function' && (
          <button
            type="button"
            className="tg-icon-btn tg-icon-btn--call"
            onClick={onCallNow}
            disabled={crmSaving}
            title="Call now"
            aria-label="Call now"
          >
            <span className="tg-icon-phone" aria-hidden />
          </button>
        )}
        {!compact && !blocked && typeof onScheduleCall === 'function' && (
          <button
            type="button"
            className="tg-icon-btn"
            onClick={onScheduleCall}
            disabled={crmSaving}
            title="Schedule call"
            aria-label="Schedule call"
          >
            <span className="tg-icon-calendar" aria-hidden />
          </button>
        )}
        {!compact && typeof onOpenMarketingMessage === 'function' && (
          <button
            type="button"
            className="tg-icon-btn tg-icon-btn--marketing"
            onClick={onOpenMarketingMessage}
            disabled={crmSaving}
            title="Marketing message"
            aria-label="View marketing message"
          >
            <span className="tg-icon-megaphone" aria-hidden />
          </button>
        )}
        {!compact && !blocked && selected?.slot && selected?.user_id != null && (
          <InboxDemoTools
            selected={selected}
            lead={lead}
            onSent={onDemoToolsSent}
            compact
          />
        )}
        {!compact && !blocked && replyAlertLevel && (
          <button
            type="button"
            className="tg-icon-btn tg-icon-btn--handled"
            onClick={onMarkHandled}
            disabled={crmSaving}
            title="Mark handled"
            aria-label="Mark handled"
          >
            ✓
          </button>
        )}
        {!compact && (
          <button
            type="button"
            className="tg-icon-btn tg-icon-btn--info"
            onClick={onOpenDetails}
            title="Lead details"
            aria-label="Lead details"
          >
            <span className="tg-icon-info" aria-hidden />
          </button>
        )}
        {!compact && (
          <button
            type="button"
            className="tg-icon-btn"
            onClick={onRefreshChat}
            disabled={refreshingChat || crmSaving}
            title="Refresh chat"
            aria-label="Refresh"
          >
            {refreshingChat ? '…' : '↻'}
          </button>
        )}
        {compact && !blocked && typeof onCallNow === 'function' && (
          <button
            type="button"
            className="tg-icon-btn tg-icon-btn--call"
            onClick={onCallNow}
            disabled={crmSaving}
            title="Call now"
            aria-label="Call now"
          >
            <span className="tg-icon-phone" aria-hidden />
          </button>
        )}
        <button
          type="button"
          className="tg-icon-btn"
          onClick={() => setMenuOpen(v => !v)}
          aria-expanded={menuOpen}
          aria-label="More actions"
          title="More"
        >
          ⋮
        </button>
        {menuOpen && (
          <div className="tg-header-menu" role="menu">
            {typeof onBackToDashboard === 'function' && (
              <button
                type="button"
                role="menuitem"
                onClick={() => { setMenuOpen(false); onBackToDashboard() }}
              >
                ← Dashboard
              </button>
            )}
            <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); onOpenDetails?.() }}>
              Lead details
            </button>
            {typeof onOpenMarketingMessage === 'function' && (
              <button
                type="button"
                role="menuitem"
                onClick={() => { setMenuOpen(false); onOpenMarketingMessage() }}
              >
                Marketing message
              </button>
            )}
            {!blocked && (
              <button
                type="button"
                role="menuitem"
                onClick={() => { setMenuOpen(false); onCallNow?.() }}
                disabled={crmSaving}
              >
                Call now
              </button>
            )}
            {!blocked && (
              <button
                type="button"
                role="menuitem"
                onClick={() => { setMenuOpen(false); onScheduleCall?.() }}
                disabled={crmSaving}
              >
                Schedule call
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              onClick={() => { setMenuOpen(false); onRefreshChat?.() }}
              disabled={refreshingChat}
            >
              Sync from Telegram
            </button>
            {typeof onExportChat === 'function' && (
              <>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => { setMenuOpen(false); onExportChat('txt') }}
                  disabled={exportingChat || refreshingChat}
                >
                  {exportingChat ? 'Exporting…' : 'Export chat (.txt)'}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => { setMenuOpen(false); onExportChat('csv') }}
                  disabled={exportingChat || refreshingChat}
                >
                  Export chat (.csv)
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => { setMenuOpen(false); onExportChat('json') }}
                  disabled={exportingChat || refreshingChat}
                >
                  Export chat (.json)
                </button>
              </>
            )}
            {!blocked && replyAlertLevel && (
              <button
                type="button"
                role="menuitem"
                onClick={() => { setMenuOpen(false); onMarkHandled?.() }}
                disabled={crmSaving}
              >
                Mark handled
              </button>
            )}
            {typeof onDeleteChat === 'function' && (
              <button
                type="button"
                role="menuitem"
                className="tg-header-menu-danger"
                onClick={() => { setMenuOpen(false); onDeleteChat() }}
                disabled={crmSaving}
              >
                Clear chat
              </button>
            )}
            {!blocked && (
              <button
                type="button"
                role="menuitem"
                className="tg-header-menu-danger"
                onClick={() => { setMenuOpen(false); onMarkSpam?.() }}
                disabled={crmSaving}
              >
                Karthik: block spam
              </button>
            )}
            {typeof onKarthikScanSpam === 'function' && (
              <button
                type="button"
                role="menuitem"
                onClick={() => { setMenuOpen(false); onKarthikScanSpam() }}
                disabled={crmSaving}
              >
                Karthik: scan all chats
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  )
}

export const ChatHeader = memo(ChatHeaderInner)
