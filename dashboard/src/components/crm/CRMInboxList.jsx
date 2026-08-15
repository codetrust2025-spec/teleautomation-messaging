import React, { useMemo, useState } from 'react'

import { CRM_STATUS_SPAM, isBlockedLead } from '../../utils/crm.js'

import { inboxAccountOwnerName } from '../../utils/accountUi.js'
import { sortConversationsByUrgency } from '../../utils/leadUx.js'

import { VirtualConversationList } from '../../inbox/VirtualConversationList.jsx'

import { InboxSidebarTools } from '../../inbox/InboxSidebarTools.jsx'



export function CRMInboxList({

  conversations,

  selected,

  mode,

  filterSlot = '',

  accountSlots = [],

  onModeChange,

  onFilterSlotChange,

  filter,

  search,

  onFilterChange,

  onSearchChange,

  onSelect,

  onKarthikScanSpam,

  onBackToDashboard,

  alertCounts = null,

  stats = null,

  dueCount = 0,

  accountInfo = {},

}) {

  const [menuOpen, setMenuOpen] = useState(false)

  const q = (search || '').trim().toLowerCase()



  const filtered = useMemo(() => {

    const list = conversations.filter(c => {

      const blocked = isBlockedLead(c)

      const st = blocked ? CRM_STATUS_SPAM : (c.crm_status || 'new')

      if (filter === 'spam') return blocked

      if (filter === 'unread') return (c.unread_count || 0) > 0 && !blocked

      if (filter === 'all') return !blocked

      if (filter === 'interested' || filter === 'follow_up' || filter === 'converted') {

        return st === filter && !blocked

      }

      return st === filter && !blocked

    }).filter(c => {

      if (!q) return true

      const hay = [

        c.name,

        c.username,

        String(c.user_id),

        c.last_message,

        c.account_id,

        inboxAccountOwnerName(c.account_id, accountInfo),

      ].join(' ').toLowerCase()

      return hay.includes(q)

    })

    return sortConversationsByUrgency(list)

  }, [conversations, filter, q, accountInfo])



  return (

    <aside className="crm-inbox-list inbox-list-panel tg-sidebar">

      <InboxSidebarTools

        mode={mode}

        filterSlot={filterSlot}

        accountSlots={accountSlots}

        onModeChange={onModeChange}

        onFilterSlotChange={onFilterSlotChange}

        filter={filter}

        search={search}

        onSearchChange={onSearchChange}

        onFilterChange={onFilterChange}

        alertCounts={alertCounts}

        stats={stats}

        dueCount={dueCount}

        menuOpen={menuOpen}

        onMenuOpenChange={setMenuOpen}

        onKarthikScanSpam={onKarthikScanSpam}

        onBackToDashboard={onBackToDashboard}

      />

      <VirtualConversationList

        conversations={filtered}

        selected={selected}

        onSelect={onSelect}

        accountInfo={accountInfo}

        showAccountOwner={mode === 'combined'}

      />

      <button

        type="button"

        className="tg-sidebar-fab"

        onClick={() => setMenuOpen(v => !v)}

        aria-label="Inbox filters and accounts"

        title="Filters & accounts"

        aria-expanded={menuOpen}

      >

        <span className="tg-sidebar-fab-icon" aria-hidden />

      </button>

    </aside>

  )

}
