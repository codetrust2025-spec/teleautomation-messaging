import React, { useState } from 'react'
import { accountLabel } from '../../utils/accountUi.js'
import { buildCallLink, callTypeLabel, formatCallScheduleTime } from '../../utils/calls.js'
import { slotTag } from '../../utils/inboxMessageUtils.js'
import { isBlockedLead, isSpamStatus } from '../../utils/crm.js'
import { getLeadScore, leadScoreLabel } from '../../utils/leadUx.js'
import { formatIstDateTime } from '../../utils/istTime.js'
import { formatPhoneDisplay } from '../../utils/whatsapp.js'
import { FollowUpControls } from './FollowUpControls.jsx'
import { NotesEditor } from './NotesEditor.jsx'
import { StatusDropdown } from './StatusDropdown.jsx'

function formatActivity(iso) {
  return formatIstDateTime(iso)
}

function leadScoreClass(score) {
  return `crm-lead-score crm-lead-score--${score || 'cold'}`
}

export function LeadDetailsPanel({
  selected,
  selectedConv,
  lead,
  scheduledCall,
  onStatusChange,
  notes,
  onNotesChange,
  onSaveNotes,
  onFollowUp2h,
  onFollowUpTomorrow,
  onScheduleCall,
  onCallNow,
  onUnblock,
  onStartCall,
  onDeleteChat,
  onClose,
  saving,
  followUpLoading,
  waStatus = null,
  onLinkPhone,
  onMoveToWhatsApp,
  linking = false,
  sendingWa = false,
}) {
  const [phoneInput, setPhoneInput] = useState('')
  if (!selected) {
    return (
      <aside className="crm-lead-panel">
        <div className="empty-state crm-lead-empty">Select a chat to manage the lead.</div>
      </aside>
    )
  }

  const username = lead?.username || ''
  const name = lead?.name || String(selected.user_id)
  const isBlocked = isBlockedLead(lead)
  const isSpam = isBlocked || isSpamStatus(lead?.status)
  const call = scheduledCall || lead?.scheduled_call
  const link = buildCallLink(call)
  const waEnabled = Boolean(waStatus?.enabled)
  const waConfigured = Boolean(waStatus?.configured)
  const linkedPhone = selectedConv?.phone_e164 || lead?.phone_e164 || ''
  const score = getLeadScore(selectedConv || {
    crm_status: lead?.status,
    crm_blocked: lead?.crm_blocked,
    unread_count: 0,
    last_user_message_at: lead?.last_user_message_at,
    last_reply_time: lead?.last_reply_at,
    reply_handled_at: lead?.reply_handled_at,
    crm_last_user_message_at: lead?.last_user_message_at,
    crm_last_reply_at: lead?.last_reply_at,
  })

  return (
    <aside className="crm-lead-panel">
      <div className="crm-lead-panel-header">
        <h3 className="crm-lead-panel-title">Lead details</h3>
        {onClose && (
          <button
            type="button"
            className="crm-lead-panel-close"
            onClick={onClose}
            aria-label="Close lead details"
          >
            ✕
          </button>
        )}
      </div>

      {!isSpam && (
        <section className="crm-lead-section crm-lead-call-actions crm-lead-call-actions--top">
          <button
            type="button"
            className="btn btn--call-now btn--block crm-call-now-btn--hero"
            onClick={() => onCallNow?.()}
            disabled={!lead || saving}
          >
            📞 Call Now
          </button>
        </section>
      )}

      <section className="crm-lead-section crm-lead-score-row">
        <span className="crm-field-label">Lead score</span>
        <span className={leadScoreClass(score)}>{leadScoreLabel(score)}</span>
      </section>

      {waEnabled && !isSpam && (
        <section className="crm-lead-section crm-lead-whatsapp">
          <span className="crm-field-label">WhatsApp</span>
          {linkedPhone ? (
            <p className="crm-lead-meta">
              Linked: <strong>{formatPhoneDisplay(linkedPhone)}</strong>
            </p>
          ) : (
            <div className="crm-lead-phone-link">
              <input
                type="tel"
                className="input input--sm"
                placeholder="9876543210"
                value={phoneInput}
                onChange={e => setPhoneInput(e.target.value)}
                disabled={linking}
              />
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={!phoneInput.trim() || linking}
                onClick={() => onLinkPhone?.(phoneInput)}
              >
                {linking ? 'Linking…' : 'Link phone'}
              </button>
            </div>
          )}
          <button
            type="button"
            className="btn btn--ghost btn--sm btn--block"
            disabled={(!linkedPhone && !selectedConv?.whatsapp_linked) || sendingWa || saving || !waConfigured}
            onClick={() => onMoveToWhatsApp?.()}
            title={waConfigured
              ? 'Send approved template to continue on WhatsApp'
              : 'Configure WHATSAPP_API_KEY on server first'}
          >
            {sendingWa ? 'Sending…' : 'Move to WhatsApp'}
          </button>
        </section>
      )}

      <section className="crm-lead-section">
        <span className="crm-field-label">User info</span>
        <p className="crm-lead-name">{name}</p>
        {username && (
          <p className="crm-lead-meta">@{String(username).replace(/^@/, '')}</p>
        )}
        <p className="crm-lead-meta">User ID: {selected.user_id}</p>
        <p className="crm-lead-meta">
          Account: {accountLabel(selected.slot)} ({slotTag(selected.slot)})
        </p>
      </section>

      {isBlocked && (
        <section className="crm-lead-section crm-lead-blocked">
          <span className="crm-field-label">Block list</span>
          <p className="crm-lead-meta crm-blocked-notice">
            This lead is blocked and hidden from the main inbox. Chat history is kept.
          </p>
          <button
            type="button"
            className="btn btn--warn btn--block"
            onClick={() => onUnblock?.()}
            disabled={!lead || saving}
          >
            Unblock
          </button>
        </section>
      )}

      <section className="crm-lead-section">
        <span className="crm-field-label">Status</span>
        <StatusDropdown
          value={isBlocked ? 'spam' : (lead?.status || 'new')}
          onChange={onStatusChange}
          disabled={saving || isBlocked}
        />
      </section>

      {!isSpam && (
        <FollowUpControls
          onRemind2h={onFollowUp2h}
          onRemindTomorrow={onFollowUpTomorrow}
          loading={followUpLoading}
          disabled={!lead}
        />
      )}

      <NotesEditor
        value={notes}
        savedValue={lead?.notes ?? ''}
        onChange={onNotesChange}
        onSave={onSaveNotes}
        saving={saving}
        disabled={!lead}
      />

      {call?.status === 'scheduled' && (
        <section className="crm-lead-section crm-lead-call">
          <span className="crm-field-label">📞 Scheduled call</span>
          <dl className="crm-activity-dl">
            <dt>Next call</dt>
            <dd>{formatCallScheduleTime(call.scheduled_time)}</dd>
            <dt>Call type</dt>
            <dd>{callTypeLabel(call.call_type)}</dd>
            {call.notes && (
              <>
                <dt>Notes</dt>
                <dd>{call.notes}</dd>
              </>
            )}
          </dl>
          <button
            type="button"
            className="btn btn--primary btn--block crm-start-call-btn"
            onClick={() => onStartCall?.(call)}
            disabled={!link.can_open}
            title={link.label}
          >
            Start Call
          </button>
          {!link.can_open && (
            <p className="crm-lead-meta crm-call-hint">{link.label}</p>
          )}
        </section>
      )}

      {!isSpam && call?.status !== 'scheduled' && (
        <section className="crm-lead-section">
          <button
            type="button"
            className="btn btn--accent btn--block"
            onClick={() => onScheduleCall?.()}
            disabled={!lead || saving}
          >
            Schedule Call
          </button>
        </section>
      )}

      <section className="crm-lead-section crm-lead-activity">
        <span className="crm-field-label">Activity</span>
        <dl className="crm-activity-dl">
          <dt>First message</dt>
          <dd>{formatActivity(lead?.first_message_at || lead?.created_at)}</dd>
          <dt>Last reply (you)</dt>
          <dd>{formatActivity(lead?.last_reply_at)}</dd>
          <dt>Last contact</dt>
          <dd>{formatActivity(lead?.last_contact_time)}</dd>
          {lead?.reminder_timestamp && !isSpam && (
            <>
              <dt>Follow-up due</dt>
              <dd>{formatActivity(lead.reminder_timestamp)}</dd>
            </>
          )}
        </dl>
      </section>

      <section className="crm-lead-section crm-lead-delete">
        <span className="crm-field-label">Danger zone</span>
        <p className="crm-lead-meta crm-delete-hint">
          Permanently clears this chat, messages, and CRM record from the dashboard.
          The conversation stays on Telegram.
        </p>
        <button
          type="button"
          className="btn btn--danger btn--block crm-delete-chat-btn"
          onClick={() => onDeleteChat?.()}
          disabled={saving}
        >
          Clear chat
        </button>
      </section>
    </aside>
  )
}
