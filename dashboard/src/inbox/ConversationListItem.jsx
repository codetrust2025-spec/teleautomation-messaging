import React, { memo } from 'react'

import { isBlockedLead } from '../utils/crm.js'

import { getReplyAlertLevel } from '../utils/replyAlert.js'

import { getLeadPriority, formatWaitingLabel } from '../utils/leadUx.js'

import { inboxAccountOwnerName } from '../utils/accountUi.js'
import { formatInboxListTime } from '../utils/inboxMessageUtils.js'

import { loadDraft } from '../utils/inboxDrafts.js'

import { avatarHue, conversationChannelBadges, displayInitials, formatUnreadCount } from './inboxUiUtils.js'



function ConversationListItemInner({

  conversation: c,

  active,

  onSelect,

  accountInfo = {},

  showAccountOwner = false,

}) {

  const alertLevel = getReplyAlertLevel(c)

  const priority = getLeadPriority(c)

  const waitingLabel = formatWaitingLabel(c)

  const blocked = isBlockedLead(c)

  const name = c.name || c.username || String(c.user_id)

  const hue = avatarHue(`${c.account_id}-${c.user_id}`)

  const unread = formatUnreadCount(c.unread_count)

  const draft = loadDraft(c.account_id, c.user_id).trim()



  let previewText = (c.last_message || '').replace(/\s+/g, ' ').trim()

  let previewClass = 'tg-conv-preview'

  if (draft) {

    previewText = draft.length > 48 ? `${draft.slice(0, 48)}…` : draft

    previewClass = 'tg-conv-preview tg-conv-preview--draft'

    previewText = `Draft: ${previewText}`

  } else if (waitingLabel && !blocked) {

    previewText = waitingLabel

    previewClass = 'tg-conv-preview tg-conv-preview--waiting'

  } else if (!previewText) {

    previewText = 'No messages yet'

    previewClass = 'tg-conv-preview tg-conv-preview--empty'

  }



  const alertClass = alertLevel === 'aggressive'

    ? ' crm-conv-item--urgent'

    : alertLevel === 'buzzer'

      ? ' crm-conv-item--delayed'

      : alertLevel === 'soft'

        ? ' crm-conv-item--waiting'

        : ''



  const showPriorityDot = priority === 'hot' || priority === 'warm' || priority === 'active'

  const priorityClass = priority === 'hot'

    ? 'tg-conv-status-dot tg-conv-status-dot--hot'

    : priority === 'warm'

      ? 'tg-conv-status-dot tg-conv-status-dot--warm'

      : 'tg-conv-status-dot tg-conv-status-dot--active'



  const listTime = formatInboxListTime(c.last_message_at)

  const ownerName = inboxAccountOwnerName(c.account_id, accountInfo)

  const ownerShort = ownerName.length > 16 ? `${ownerName.slice(0, 14)}…` : ownerName
  const channelBadges = conversationChannelBadges(c)
  const showChannelBadges = channelBadges.includes('wa')

  return (

    <button

      type="button"

      className={`tg-conv-row inbox-conv-item crm-conv-item${active ? ' inbox-conv-item--active tg-conv-row--active' : ''}${c.crm_reminder_due && !blocked ? ' crm-conv-item--due' : ''}${blocked ? ' crm-conv-item--spam' : ''}${alertClass}`}

      onClick={() => onSelect?.(c)}

    >

      <span className="tg-conv-avatar-wrap">

        <span

          className="tg-conv-avatar"

          style={{ '--tg-avatar-hue': hue }}

          aria-hidden

        >

          {displayInitials(name)}

        </span>

        {showPriorityDot && (

          <span

            className={priorityClass}

            title={priority === 'hot' ? 'Urgent' : priority === 'warm' ? 'Warm' : 'Active'}

            aria-hidden

          />

        )}

      </span>



      <div className="tg-conv-body">

        <div className="tg-conv-row-top">

          <span className="tg-conv-name">
            {showChannelBadges && (
              <span className="tg-conv-channels" aria-hidden>
                {channelBadges.map(ch => (
                  <span
                    className={`inbox-channel-badge inbox-channel-badge--${ch === 'wa' ? 'wa' : 'tg'} tg-conv-channel`}
                    key={ch}
                  >
                    {ch === 'wa' ? 'WA' : 'TG'}
                  </span>
                ))}
              </span>
            )}
            {name}
          </span>

          {blocked && <span className="tg-conv-muted" aria-label="Blocked" title="Blocked">🔇</span>}

        </div>

        <div className="tg-conv-preview-row">

          <span className={previewClass}>{previewText}</span>

        </div>

      </div>



      <div className="tg-conv-meta">
        <span className="tg-conv-meta-time">{listTime}</span>
      </div>

      {unread ? (
        <span className="tg-conv-unread">{unread}</span>
      ) : !active && showAccountOwner && ownerName ? (
        <span
          className="tg-conv-slot tg-conv-slot--corner tg-conv-slot--owner"
          title={ownerName}
        >
          {ownerShort}
        </span>
      ) : null}

    </button>

  )

}



export const ConversationListItem = memo(ConversationListItemInner)
