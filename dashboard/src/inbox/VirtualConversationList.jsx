import React, { useCallback, useEffect, useState } from 'react'
import { VirtualList } from './VirtualList.jsx'
import { ConversationListItem } from './ConversationListItem.jsx'

function useMobileConvList() {
  const [mobile, setMobile] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const onChange = () => setMobile(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return mobile
}

/** Row height matches .tg-conv-row in inboxLayout.css */
export const CONVERSATION_ROW_HEIGHT = 72

export function VirtualConversationList({
  conversations,
  selected,
  onSelect,
  accountInfo = {},
  showAccountOwner = false,
  emptyMessage = 'No conversations match this filter.',
}) {
  const mobileList = useMobileConvList()
  const renderRow = useCallback((c) => {
    const active = selected?.slot === c.account_id
      && Number(selected.user_id) === Number(c.user_id)
    return (
      <ConversationListItem
        conversation={c}
        active={active}
        onSelect={onSelect}
        accountInfo={accountInfo}
        showAccountOwner={showAccountOwner}
      />
    )
  }, [selected, onSelect, accountInfo, showAccountOwner])

  if (!conversations.length) {
    return <div className="empty-state inbox-empty tg-conv-empty">{emptyMessage}</div>
  }

  if (mobileList || conversations.length < 80) {
    return (
      <div className="tg-conv-list tg-conv-list--static">
        {conversations.map(c => {
          const key = `${c.account_id}-${c.user_id}`
          const active = selected?.slot === c.account_id
            && Number(selected.user_id) === Number(c.user_id)
          return (
            <ConversationListItem
              key={key}
              conversation={c}
              active={active}
              onSelect={onSelect}
              accountInfo={accountInfo}
              showAccountOwner={showAccountOwner}
            />
          )
        })}
      </div>
    )
  }

  return (
    <VirtualList
      className="tg-conv-list tg-conv-list--virtual"
      items={conversations}
      itemHeight={CONVERSATION_ROW_HEIGHT}
      getKey={(c) => `${c.account_id}-${c.user_id}`}
      renderItem={renderRow}
    />
  )
}
