import React, { useState } from 'react'
import { isBlockedLead } from '../../utils/crm.js'
import { getReplyAlertLevel } from '../../utils/replyAlert.js'
import { CallScheduledBanner } from './CallScheduledBanner.jsx'
import { ChatHeader } from '../../inbox/ChatHeader.jsx'
import { MessageTimeline } from '../../inbox/MessageTimeline.jsx'
import { ChatComposer } from '../../inbox/ChatComposer.jsx'
import { CallStatusBar } from '../../inbox/CallStatusBar.jsx'
import { voiceStatusLabel } from '../../inbox/voiceCallEvents.js'
import { InboxMarketingMessageModal } from '../../inbox/InboxMarketingMessageModal.jsx'

export function ChatWindow({
  selected,
  selectedConv,
  accountInfo = {},
  postingModes = {},
  onBack,
  onBackToDashboard,
  onOpenDetails,
  onRefreshChat,
  refreshingChat = false,
  onLoadOlderMessages,
  loadingOlderMessages = false,
  canLoadOlderMessages = false,
  messages,
  loadingMessages,
  replyText,
  onReplyChange,
  onSend,
  onSendMedia,
  sending,
  sendingMedia = false,
  error,
  showNewMessages,
  onJumpToLatest,
  messagesScrollRef,
  onMessagesScroll,
  messagesEndRef,
  onQuickReply,
  onScheduleCall,
  onCallNow,
  onMarkSpam,
  onKarthikScanSpam,
  onMarkHandled,
  onDeleteChat,
  onEditMessage,
  onDeleteMessage,
  replyToMessage = null,
  onClearReply,
  onReplyToMessage,
  onForwardMessage,
  onQuickReaction,
  selectMode = false,
  selectedMessageIds,
  onToggleSelect,
  onEnterSelectMode,
  onExitSelectMode,
  onCopySelected,
  onDeleteSelected,
  onExportChat,
  exportingChat = false,
  onAiSuggest,
  aiSuggesting = false,
  aiSuggestion = null,
  onDiscardAiSuggestion,
  crmSaving,
  scheduledCall,
  outgoingCall = null,
  onOutgoingCallExpand,
  onOutgoingCallEnd,
  whatsappEnabled = false,
  whatsappConfigured = false,
  replyChannel = 'telegram',
  onReplyChannelChange,
  lead = null,
  onDemoToolsSent,
}) {
  const [marketingOpen, setMarketingOpen] = useState(false)
  const postingModeConfig = selected?.slot ? postingModes[selected.slot] : null

  if (!selected) {
    return (
      <section className="crm-chat-window inbox-chat-panel tg-chat-pane">
        <div className="empty-state inbox-chat-empty tg-chat-empty">
          Select a conversation to start messaging.
        </div>
      </section>
    )
  }

  const blocked = isBlockedLead(selectedConv)
  const replyAlertLevel = getReplyAlertLevel(selectedConv)
  return (
    <section className="crm-chat-window inbox-chat-panel tg-chat-pane">
      <ChatHeader
        selected={selected}
        selectedConv={selectedConv}
        accountInfo={accountInfo}
        onBack={onBack}
        onBackToDashboard={onBackToDashboard}
        onOpenDetails={onOpenDetails}
        onCallNow={onCallNow}
        onScheduleCall={onScheduleCall}
        onMarkSpam={onMarkSpam}
        onKarthikScanSpam={onKarthikScanSpam}
        onMarkHandled={onMarkHandled}
        onDeleteChat={onDeleteChat}
        onExportChat={onExportChat}
        exportingChat={exportingChat}
        onRefreshChat={onRefreshChat}
        onOpenMarketingMessage={() => setMarketingOpen(true)}
        lead={lead}
        onDemoToolsSent={onDemoToolsSent}
        refreshingChat={refreshingChat}
        crmSaving={crmSaving}
        blocked={blocked}
        replyAlertLevel={replyAlertLevel}
      />

      {outgoingCall?.minimized && (
        <CallStatusBar
          name={outgoingCall.name}
          seed={outgoingCall.seed}
          statusLabel={voiceStatusLabel(outgoingCall.status, { error: outgoingCall.error })}
          onExpand={onOutgoingCallExpand}
          onEnd={onOutgoingCallEnd}
        />
      )}

      {replyAlertLevel && !blocked && (
        <div className={`crm-reply-alert-banner crm-reply-alert-banner--${replyAlertLevel}`} role="status">
          {replyAlertLevel === 'aggressive'
            ? '⚠ No reply for 20+ minutes — urgent'
            : replyAlertLevel === 'buzzer'
              ? 'No reply for 10+ minutes — buzzer active'
              : 'No reply for 5+ minutes — respond soon'}
        </div>
      )}

      <CallScheduledBanner call={scheduledCall || selectedConv?.crm_scheduled_call} />

      <div className="inbox-chat-messages-wrap tg-chat-body">
        {showNewMessages && (
          <button
            type="button"
            className="inbox-new-messages-pill tg-scroll-down"
            onClick={onJumpToLatest}
            aria-label="Scroll to new messages"
          >
            ↓
          </button>
        )}
        <div
          className="inbox-messages chat-container tg-messages-scroll"
          ref={messagesScrollRef}
          onScroll={onMessagesScroll}
          role="log"
          aria-live="polite"
        >
          <div className="inbox-messages-inner tg-messages-inner">
            {canLoadOlderMessages && !loadingMessages && (
              <div className="inbox-load-older-wrap">
                <button
                  type="button"
                  className="inbox-load-older-btn"
                  onClick={onLoadOlderMessages}
                  disabled={loadingOlderMessages || !onLoadOlderMessages}
                >
                  {loadingOlderMessages ? 'Loading previous…' : 'Load previous messages'}
                </button>
              </div>
            )}
            <MessageTimeline
              messages={messages}
              loadingMessages={loadingMessages}
              messagesEndRef={messagesEndRef}
              chatSlot={selected.slot}
              chatUserId={selected.user_id}
              selectedConv={selectedConv}
              whatsappEnabled={whatsappEnabled}
              blocked={blocked}
              onEditMessage={onEditMessage}
              onDeleteMessage={onDeleteMessage}
              onReplyToMessage={onReplyToMessage}
              onForwardMessage={onForwardMessage}
              onQuickReaction={onQuickReaction}
              selectMode={selectMode}
              selectedMessageIds={selectedMessageIds}
              onToggleSelect={onToggleSelect}
              onEnterSelectMode={onEnterSelectMode}
            />
          </div>
        </div>
      </div>

      {blocked && (
        <div className="crm-blocked-compose-notice" role="status">
          Lead is blocked — replies disabled. Unblock from the right panel to interact again.
        </div>
      )}

      {aiSuggestion && !blocked && (
        <div className="crm-ai-suggestion-banner" role="status">
          <span className="crm-ai-suggestion-badge">Karthik draft</span>
          <span className="crm-ai-suggestion-text">
            {aiSuggestion.stage ? `${aiSuggestion.stage} · ` : ''}
            {typeof aiSuggestion.confidence === 'number'
              ? `${Math.round(aiSuggestion.confidence * 100)}% confidence · `
              : ''}
            Review and edit before sending.
          </span>
          <button
            type="button"
            className="crm-ai-suggestion-discard"
            onClick={onDiscardAiSuggestion}
          >
            Dismiss
          </button>
        </div>
      )}

      {selectMode && (
        <div className="tg-select-bar" role="toolbar" aria-label="Message selection">
          <span className="tg-select-bar-count">
            {(selectedMessageIds?.size ?? 0)} selected
          </span>
          <div className="tg-select-bar-actions">
            <button type="button" className="btn btn--ghost btn--sm" onClick={onCopySelected}>
              Copy
            </button>
            <button type="button" className="btn btn--ghost btn--sm" onClick={onDeleteSelected}>
              Delete
            </button>
            <button type="button" className="btn btn--ghost btn--sm" onClick={onExitSelectMode}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <ChatComposer
        replyText={replyText}
        onReplyChange={onReplyChange}
        onSend={onSend}
        onSendMedia={onSendMedia}
        sending={sending}
        sendingMedia={sendingMedia}
        blocked={blocked}
        error={error}
        replyToMessage={replyToMessage}
        onClearReply={onClearReply}
        whatsappEnabled={whatsappEnabled}
        whatsappConfigured={whatsappConfigured}
        selectedConv={selectedConv}
        replyChannel={replyChannel}
        onReplyChannelChange={onReplyChannelChange}
      />

      <InboxMarketingMessageModal
        open={marketingOpen}
        onClose={() => setMarketingOpen(false)}
        slot={selected.slot}
        postingModeConfig={postingModeConfig}
      />
    </section>
  )
}
