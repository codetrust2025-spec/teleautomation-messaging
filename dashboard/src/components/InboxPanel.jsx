import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { API } from '../config.js'
import { accountLabel } from '../utils/accountUi.js'
import {
  applyCrmBlockFlags,
  isBlockedInCrmState,
  isBlockedLead,
  markReplyHandled,
  patchLead,
  scheduleFollowUp,
  unblockLead,
} from '../utils/crm.js'
import { karthikBlockChat, karthikScanAndBlockSpam, karthikSpamCheck } from '../utils/karthikSpam.js'
import {
  REPLY_CHECK_INTERVAL_MS,
  countAlertConversationsByLevel,
  formatUrgentTopBanner,
} from '../utils/replyAlert.js'
import { sortConversationsByUrgency } from '../utils/leadUx.js'
import {
  buildCallLink,
  buildCallSystemMessage,
  completeCall,
  getScheduledCall,
  scheduleCall,
} from '../utils/calls.js'
import { unlockNotificationSound } from '../utils/notificationSound.js'
import {
  LIVE_EVENTS,
  appendMessageDeduped,
  applyMessageStatus,
  applyOutboundLiveMessage,
  applyReadUpTo,
  isUserNearBottom,
  mergeMessageLists,
  oldestTelegramMessageId,
  removeMessageById,
  replacePendingMessage,
  sameUser,
  canDeleteOutboundMessage,
} from '../utils/inboxMessageUtils.js'
import {
  deleteInboxMessage,
  patchInboxMessage,
} from '../utils/inboxMessageActions.js'
import { useConfirm } from '../context/ConfirmContext.jsx'
import { clearDraft, loadDraft, saveDraft } from '../utils/inboxDrafts.js'
import { copyToClipboard } from '../utils/copyToClipboard.js'
import { deleteInboxConversation } from '../utils/deleteChat.js'
import { downloadInboxChatExport } from '../utils/exportInboxChat.js'
import { fetchCrmState } from '../utils/crm.js'
import { getScrollTop, setScrollTop } from '../utils/inboxScrollCache.js'
import { CallOutcomeModal } from './crm/CallOutcomeModal.jsx'
import { CallReminderBanner } from './crm/CallReminderBanner.jsx'
import { ChatWindow } from './crm/ChatWindow.jsx'
import { CRMInboxList } from './crm/CRMInboxList.jsx'
import { LeadDetailsPanel } from './crm/LeadDetailsPanel.jsx'
import { CallNowModal } from './crm/CallNowModal.jsx'
import { ScheduleCallModal } from './crm/ScheduleCallModal.jsx'
import { DeleteChatModal } from './crm/DeleteChatModal.jsx'
import { OutgoingCallOverlay } from '../inbox/OutgoingCallOverlay.jsx'
import { useTelegramVoiceCall } from '../inbox/useTelegramVoiceCall.js'
import { isTerminalVoiceStatus } from '../inbox/voiceCallEvents.js'
import { useAuth } from '../context/AuthContext.jsx'
import { mediaTypeFromFile, pickReplyChannel } from '../inbox/inboxUiUtils.js'
import {
  fetchWhatsAppStatus,
  linkLeadPhone,
  sendWhatsAppTemplate,
} from '../utils/whatsapp.js'

const OUTBOUND_MEDIA_LABELS = {
  photo: '[photo]',
  video: '[video]',
  voice: '[voice]',
  audio: '[audio]',
  document: '[document]',
}

export function InboxPanel({
  inboxState,
  inboxLiveQueueRef,
  inboxLiveTick,
  onInboxPatch,
  accountSlots,
  accountInfo = {},
  postingModes = {},
  crmState,
  onCrmUpdate,
  onBackToDashboard,
  openChatTarget = null,
}) {
  const { username: authUsername } = useAuth()
  const { confirm } = useConfirm()
  const [mode, setMode] = useState('combined')
  const [filterSlot, setFilterSlot] = useState(accountSlots[0] || 'account1')
  const [crmFilter, setCrmFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const [messages, setMessages] = useState([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [replyText, setReplyText] = useState('')
  const [replyToMessage, setReplyToMessage] = useState(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedMessageIds, setSelectedMessageIds] = useState(() => new Set())
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [showNewMessages, setShowNewMessages] = useState(false)
  const [notes, setNotes] = useState('')
  const [crmSaving, setCrmSaving] = useState(false)
  const [followUpLoading, setFollowUpLoading] = useState(false)
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false)
  const [callNowOpen, setCallNowOpen] = useState(false)
  const [callScheduling, setCallScheduling] = useState(false)
  const [outcomeCall, setOutcomeCall] = useState(null)
  const [outcomeSaving, setOutcomeSaving] = useState(false)
  const skippedOutcomeIdsRef = useRef(new Set())
  const [replyCheckTick, setReplyCheckTick] = useState(0)
  const [toast, setToast] = useState(null)
  const [leadDetailsOpen, setLeadDetailsOpen] = useState(false)
  const [refreshingChat, setRefreshingChat] = useState(false)
  const [exportingChat, setExportingChat] = useState(false)
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false)
  const [canLoadOlderMessages, setCanLoadOlderMessages] = useState(true)
  const loadingOlderRef = useRef(false)
  const [aiSuggesting, setAiSuggesting] = useState(false)
  const [aiSuggestion, setAiSuggestion] = useState(null)
  const [deleteChatOpen, setDeleteChatOpen] = useState(false)
  const [deleteChatLoading, setDeleteChatLoading] = useState(false)
  const [deleteChatError, setDeleteChatError] = useState('')
  const [waStatus, setWaStatus] = useState(null)
  const [linkingPhone, setLinkingPhone] = useState(false)
  const [sendingWa, setSendingWa] = useState(false)
  const [replyChannel, setReplyChannel] = useState('telegram')

  const loadSeqRef = useRef(0)
  const spamScanDoneRef = useRef(false)
  const spamCheckSeqRef = useRef(0)
  const prevSelectedRef = useRef(null)
  const sendingRef = useRef(false)
  const messagesScrollRef = useRef(null)
  const messagesEndRef = useRef(null)
  const stickToBottomRef = useRef(true)
  const forceScrollRef = useRef(false)
  const lastMessageCountRef = useRef(0)
  const onInboxPatchRef = useRef(onInboxPatch)
  onInboxPatchRef.current = onInboxPatch

  const leadDetail = useMemo(() => {
    if (!selected) return null
    const key = `${selected.slot}:${selected.user_id}`
    const lead = crmState?.leads?.[key] || null
    const call = getScheduledCall(crmState, selected.slot, selected.user_id)
    if (!lead) return call ? { scheduled_call: call } : null
    return { ...lead, scheduled_call: call || lead.scheduled_call }
  }, [selected, crmState?.leads, crmState?.scheduled_calls])

  useEffect(() => {
    if (leadDetail) {
      setNotes(leadDetail.notes || '')
    } else {
      setNotes('')
    }
  }, [leadDetail?.notes, selected?.slot, selected?.user_id])

  useEffect(() => {
    fetchWhatsAppStatus().then(setWaStatus).catch(() => setWaStatus(null))
  }, [])

  const snapScrollToBottom = useCallback(() => {
    const el = messagesScrollRef.current
    if (!el) return
    el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight)
  }, [])

  const scrollToBottom = useCallback(({ smooth = false } = {}) => {
    const el = messagesScrollRef.current
    if (!el) return
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    } else {
      snapScrollToBottom()
    }
  }, [snapScrollToBottom])

  const jumpToLatest = useCallback(() => {
    stickToBottomRef.current = true
    forceScrollRef.current = true
    setShowNewMessages(false)
    scrollToBottom({ smooth: false })
  }, [scrollToBottom])

  const handleMessagesScroll = useCallback(() => {
    const el = messagesScrollRef.current
    if (!el) return
    stickToBottomRef.current = isUserNearBottom(el)
    if (stickToBottomRef.current) setShowNewMessages(false)
  }, [])

  const persistDraftAndScroll = useCallback((sel) => {
    if (!sel) return
    saveDraft(sel.slot, sel.user_id, replyText)
    const el = messagesScrollRef.current
    if (el) setScrollTop(sel.slot, sel.user_id, el.scrollTop)
  }, [replyText])

  const selectConversation = useCallback((c) => {
    if (!c) return
    unlockNotificationSound()
    persistDraftAndScroll(prevSelectedRef.current)
    const next = { slot: c.account_id, user_id: c.user_id }
    prevSelectedRef.current = next
    setSelected(next)
    setLeadDetailsOpen(false)
    setReplyText(loadDraft(c.account_id, c.user_id))
    setAiSuggestion(null)
    setError('')
    const cachedScroll = getScrollTop(c.account_id, c.user_id)
    stickToBottomRef.current = cachedScroll == null
    forceScrollRef.current = cachedScroll == null
    setShowNewMessages(false)
  }, [persistDraftAndScroll])

  const closeConversation = useCallback(() => {
    persistDraftAndScroll(prevSelectedRef.current)
    prevSelectedRef.current = null
    setSelected(null)
    setLeadDetailsOpen(false)
    setReplyText('')
    setAiSuggestion(null)
    setError('')
  }, [persistDraftAndScroll])

  useEffect(() => {
    if (!selected) setLeadDetailsOpen(false)
  }, [selected])

  useEffect(() => {
    if (spamScanDoneRef.current) return undefined
    spamScanDoneRef.current = true
    let cancelled = false
    ;(async () => {
      try {
        const data = await karthikScanAndBlockSpam()
        if (cancelled) return
        const n = Number(data.blocked_count) || 0
        if (n > 0) {
          setToast(`Karthik blocked ${n} spam chat${n === 1 ? '' : 's'}`)
          onCrmUpdate?.(data.crm)
          onInboxPatchRef.current?.()
        }
      } catch {
        /* scan optional */
      }
    })()
    return () => { cancelled = true }
  }, [onCrmUpdate])

  const stampConv = useCallback(
    (c, slot) => applyCrmBlockFlags({ ...c, account_id: slot || c.account_id }, crmState),
    [crmState],
  )

  const conversations = useMemo(() => {
    if (!inboxState?.slots) return []
    if (mode === 'combined') {
      const list = []
      for (const slot of accountSlots) {
        const block = inboxState.slots[slot]
        if (!block?.conversations) continue
        for (const c of block.conversations) {
          list.push(stampConv(c, slot))
        }
      }
      return sortConversationsByUrgency(list)
    }
    return sortConversationsByUrgency(
      (inboxState.slots[filterSlot]?.conversations || []).map(c => stampConv(c, filterSlot)),
    )
  }, [inboxState, mode, filterSlot, accountSlots, replyCheckTick, stampConv])

  const alertCounts = useMemo(
    () => countAlertConversationsByLevel(inboxState),
    [inboxState, replyCheckTick],
  )

  // Reply-SLA sound is driven by GlobalNotificationSounds so that a delayed
  // conversation is heard on any page, not only while this panel is mounted.
  // The badge counts above stay here because they are this panel's UI.

  useEffect(() => {
    const id = window.setInterval(() => setReplyCheckTick(t => t + 1), REPLY_CHECK_INTERVAL_MS)
    const resync = () => setReplyCheckTick(t => t + 1)
    window.addEventListener('crm-buzzer-toggle', resync)
    window.addEventListener('sound-quiet-hours-change', resync)
    return () => {
      clearInterval(id)
      window.removeEventListener('crm-buzzer-toggle', resync)
      window.removeEventListener('sound-quiet-hours-change', resync)
    }
  }, [])

  const selectedConv = conversations.find(
    c => selected
      && c.account_id === selected.slot
      && sameUser(c.user_id, selected.user_id),
  )

  useEffect(() => {
    if (selected) {
      setReplyChannel(pickReplyChannel(messages, selectedConv))
    }
  }, [selected?.slot, selected?.user_id, selectedConv, messages.length])

  useEffect(() => {
    if (!openChatTarget?.slot || openChatTarget.user_id == null) return
    const match = conversations.find(
      c => c.account_id === openChatTarget.slot
        && sameUser(c.user_id, openChatTarget.user_id),
    )
    if (match) {
      selectConversation(match)
      return
    }
    if (
      selected?.slot === openChatTarget.slot
      && sameUser(selected.user_id, openChatTarget.user_id)
    ) {
      return
    }
    const next = { slot: openChatTarget.slot, user_id: openChatTarget.user_id }
    prevSelectedRef.current = next
    setSelected(next)
    setLeadDetailsOpen(false)
    setReplyText(loadDraft(openChatTarget.slot, openChatTarget.user_id))
    setAiSuggestion(null)
    setError('')
    stickToBottomRef.current = true
    forceScrollRef.current = true
    setShowNewMessages(false)
  }, [openChatTarget, conversations, selectConversation, selected])

  const selectedCall = useMemo(() => {
    if (!selected) return null
    return getScheduledCall(crmState, selected.slot, selected.user_id)
      || selectedConv?.crm_scheduled_call
      || null
  }, [selected, selectedConv, crmState?.scheduled_calls])

  useEffect(() => {
    if (!selected) return undefined
    if (isBlockedLead(selectedConv) || isBlockedInCrmState(crmState, selected.slot, selected.user_id)) {
      closeConversation()
      return undefined
    }
    if (loadingMessages) return undefined
    const seq = ++spamCheckSeqRef.current
    let cancelled = false
    ;(async () => {
      try {
        const verdict = await karthikSpamCheck(selected.slot, selected.user_id)
        if (cancelled || seq !== spamCheckSeqRef.current) return
        if (!verdict.is_spam || Number(verdict.confidence) < 0.5) return
        const data = await karthikBlockChat(selected.slot, selected.user_id)
        if (cancelled || seq !== spamCheckSeqRef.current) return
        onCrmUpdate?.(data.crm, data.lead)
        onInboxPatchRef.current?.()
        setToast('Karthik blocked spam — see Spam / Blocked filter')
        closeConversation()
      } catch (e) {
        setError(String(e.message || e))
      }
    })()
    return () => { cancelled = true }
  }, [
    selected?.slot,
    selected?.user_id,
    loadingMessages,
    selectedConv?.crm_blocked,
    crmState?.block_list,
    closeConversation,
    crmState?.leads,
  ])

  useEffect(() => {
    if (!selected || !inboxLiveQueueRef?.current?.length) return
    const queue = inboxLiveQueueRef.current
    let i = 0
    while (i < queue.length) {
      const ev = queue[i]
      if (!LIVE_EVENTS.has(ev.event) || ev.slot !== selected.slot) {
        i += 1
        continue
      }
      const uid = ev.conversation?.user_id ?? ev.message?.user_id
      if (uid != null && !sameUser(uid, selected.user_id)) {
        i += 1
        continue
      }
      queue.splice(i, 1)
      if (ev.event === 'message_read') {
        setMessages(prev => applyReadUpTo(prev, ev.message?.max_id))
        continue
      }
      if (ev.event === 'message_status') {
        setMessages(prev => applyMessageStatus(prev, ev.message))
        continue
      }
      if (ev.event === 'message_deleted') {
        const delId = ev.message?.id
        if (delId != null) {
          setMessages(prev => removeMessageById(prev, delId))
        }
        continue
      }
      if (!ev.message) continue
      const msg = ev.message
      if (msg.direction === 'in' || ev.event === 'new_message') {
        setMessages(prev => appendMessageDeduped(prev, msg))
        stickToBottomRef.current = true
        forceScrollRef.current = true
      } else {
        setMessages(prev => applyOutboundLiveMessage(prev, msg))
      }
    }
  }, [inboxLiveTick, selected, inboxLiveQueueRef])

  useEffect(() => {
    const el = messagesScrollRef.current
    const prevCount = lastMessageCountRef.current
    const count = messages.length
    lastMessageCountRef.current = count
    const grew = count > prevCount

    const runScrollDecision = () => {
      if (loadingOlderRef.current) return
      const force = forceScrollRef.current
      forceScrollRef.current = false
      if (force || loadingMessages) {
        scrollToBottom({ smooth: false })
        stickToBottomRef.current = true
        setShowNewMessages(false)
        return
      }
      if (!grew) return
      const near = stickToBottomRef.current || (el ? isUserNearBottom(el) : false)
      stickToBottomRef.current = near
      if (near) {
        scrollToBottom({ smooth: false })
        setShowNewMessages(false)
      } else {
        setShowNewMessages(true)
      }
    }
    requestAnimationFrame(() => requestAnimationFrame(runScrollDecision))
  }, [messages, selected, scrollToBottom, loadingMessages])

  useEffect(() => {
    if (!selected || loadingMessages || messages.length === 0) return
    const cached = getScrollTop(selected.slot, selected.user_id)
    if (cached != null) {
      const el = messagesScrollRef.current
      if (el) {
        requestAnimationFrame(() => {
          el.scrollTop = cached
          stickToBottomRef.current = isUserNearBottom(el)
        })
      }
      return
    }
    stickToBottomRef.current = true
    forceScrollRef.current = true
    setShowNewMessages(false)
  }, [loadingMessages, selected?.slot, selected?.user_id, messages.length])

  useEffect(() => {
    if (!selected) {
      setMessages([])
      setError('')
      setReplyText('')
      return undefined
    }
    const { slot, user_id: userId } = selected
    const seq = ++loadSeqRef.current
    setMessages([])
    setLoadingMessages(true)
    setCanLoadOlderMessages(true)
    setError('')
    const controller = new AbortController()
    const applyMessages = (data, { merge = false } = {}) => {
      if (seq !== loadSeqRef.current) return
      if (data.status !== 'ok') {
        setError(data.message || 'Failed to load messages')
        return
      }
      const rows = data.messages || []
      if (merge) {
        setMessages(prev => mergeMessageLists(rows, prev))
      } else {
        setMessages(rows)
      }
    }
    ;(async () => {
      try {
        const fastRes = await fetch(
          `${API}/inbox/${encodeURIComponent(slot)}/messages/${userId}?sync=0`,
          { signal: controller.signal, cache: 'no-store' },
        )
        if (!fastRes.ok) throw new Error(fastRes.status === 404 ? 'Not found' : `HTTP ${fastRes.status}`)
        const fastData = await fastRes.json()
        applyMessages(fastData, { merge: false })
        if (fastData.status === 'ok') {
          fetch(`${API}/inbox/${encodeURIComponent(slot)}/read/${userId}`, {
            method: 'POST',
          })
            .then(r => r.json())
            .then((readData) => {
              if (readData?.lead) {
                onCrmUpdate?.(readData.crm, readData.lead)
              }
            })
            .catch(() => {})
        }
      } catch (e) {
        if (seq !== loadSeqRef.current || e.name === 'AbortError') return
        setError(e.message?.includes('fetch') ? 'Could not reach server' : e.message)
      } finally {
        if (seq === loadSeqRef.current) setLoadingMessages(false)
      }
      if (seq !== loadSeqRef.current) return
      try {
        const fullRes = await fetch(
          `${API}/inbox/${encodeURIComponent(slot)}/messages/${userId}?sync=1`,
          { signal: controller.signal, cache: 'no-store' },
        )
        if (!fullRes.ok) return
        applyMessages(await fullRes.json(), { merge: true })
      } catch {
        /* Telegram sync optional */
      }
    })()
    return () => controller.abort()
  }, [selected?.slot, selected?.user_id])

  useEffect(() => {
    if (!selected || !selectedConv?.last_message_at || loadingMessages) return undefined
    const { slot, user_id: userId } = selected
    const controller = new AbortController()
    ;(async () => {
      try {
        const res = await fetch(
          `${API}/inbox/${encodeURIComponent(slot)}/messages/${userId}?sync=0`,
          { signal: controller.signal, cache: 'no-store' },
        )
        if (!res.ok) return
        const data = await res.json()
        if (data.status === 'ok' && Array.isArray(data.messages)) {
          setMessages(prev => mergeMessageLists(data.messages, prev))
        }
      } catch {
        /* ignore background refresh errors */
      }
    })()
    return () => controller.abort()
  }, [selected?.slot, selected?.user_id, selectedConv?.last_message_at, loadingMessages])

  useEffect(() => {
    if (mode === 'per_account' && filterSlot && selected && selected.slot !== filterSlot) {
      setSelected(null)
    }
  }, [mode, filterSlot, selected])

  useEffect(() => {
    setReplyToMessage(null)
    setSelectMode(false)
    setSelectedMessageIds(new Set())
  }, [selected?.slot, selected?.user_id])

  const handleReplyToMessage = useCallback((message) => {
    if (!message) return
    setReplyToMessage(message)
    setSelectMode(false)
    setSelectedMessageIds(new Set())
  }, [])

  const handleForwardMessage = useCallback(async (message) => {
    const text = (message?.text || '').trim()
    if (!text) {
      setToast('No text to copy')
      return
    }
    const ok = await copyToClipboard(text)
    setToast(ok ? 'Copied — paste in another chat' : 'Copy failed')
  }, [])

  const handleEnterSelectMode = useCallback((messageId) => {
    setSelectMode(true)
    if (messageId != null) {
      setSelectedMessageIds(new Set([messageId]))
    }
  }, [])

  const handleExitSelectMode = useCallback(() => {
    setSelectMode(false)
    setSelectedMessageIds(new Set())
  }, [])

  const handleToggleSelect = useCallback((messageId) => {
    setSelectedMessageIds(prev => {
      const next = new Set(prev)
      if (next.has(messageId)) next.delete(messageId)
      else next.add(messageId)
      return next
    })
  }, [])

  const handleCopySelected = useCallback(async () => {
    const lines = (messages || [])
      .filter(m => selectedMessageIds.has(m.id))
      .map(m => (m.text || '').trim())
      .filter(Boolean)
    if (!lines.length) {
      setToast('No text in selection')
      return
    }
    const ok = await copyToClipboard(lines.join('\n\n'))
    setToast(ok ? `Copied ${lines.length} message(s)` : 'Copy failed')
  }, [messages, selectedMessageIds])

  const handleDeleteSelected = useCallback(async () => {
    if (!selected) return
    const ids = [...selectedMessageIds]
    const deletable = (messages || []).filter(
      m => ids.includes(m.id) && canDeleteOutboundMessage(m, { blocked: isBlockedLead(selectedConv) }),
    )
    if (!deletable.length) {
      setToast('No deletable outbound messages selected')
      return
    }
    const ok = await confirm({
      title: 'Delete messages?',
      message: `Delete ${deletable.length} message(s) in Telegram? This cannot be undone.`,
      variant: 'danger',
      confirmLabel: 'Delete',
    })
    if (!ok) return
    for (const m of deletable) {
      try {
        const data = await deleteInboxMessage(selected.slot, selected.user_id, Number(m.id))
        if (data.status === 'ok') {
          setMessages(prev => removeMessageById(prev, Number(m.id)))
        }
      } catch {
        /* continue */
      }
    }
    setToast('Selected messages deleted')
    handleExitSelectMode()
    onInboxPatchRef.current?.()
  }, [selected, selectedMessageIds, messages, selectedConv, confirm, handleExitSelectMode])

  const handleQuickReaction = useCallback(async (emoji, message) => {
    if (!selected || !message || sendingRef.current) return
    const replyId = Number(message.id)
    if (!Number.isFinite(replyId)) return
    setSending(true)
    setError('')
    try {
      const res = await fetch(`${API}/inbox/${encodeURIComponent(selected.slot)}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: selected.user_id,
          text: emoji,
          sent_by: 'manual',
          reply_to_message_id: replyId,
        }),
      })
      const data = await res.json()
      if (data.status !== 'ok') {
        setError(data.message || 'Reaction failed')
        return
      }
      if (data.message) {
        setMessages(prev => appendMessageDeduped(prev, data.message))
      }
      onInboxPatchRef.current?.()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setSending(false)
    }
  }, [selected])

  async function sendReply() {
    if (!selected || !replyText.trim() || sendingRef.current) return
    const text = replyText.trim()
    const operatorLabel = (authUsername || 'Operator').trim()
    const pendingId = `pending-${Date.now()}`
    const optimistic = {
      id: pendingId,
      chat_id: selected.user_id,
      account_id: selected.slot,
      direction: 'out',
      text,
      timestamp: new Date().toISOString(),
      status: 'sending',
      read_at: null,
      sent_by: aiSuggestion?.text ? 'ai_approved' : 'manual',
      sender_name: operatorLabel,
      ...(replyChannel === 'whatsapp' && waStatus?.enabled ? { channel: 'whatsapp' } : {}),
    }
    sendingRef.current = true
    setSending(true)
    setError('')
    stickToBottomRef.current = true
    forceScrollRef.current = true
    setShowNewMessages(false)
    setMessages(prev => [...prev, optimistic])
    const suggestionActive = Boolean(aiSuggestion?.text)
    setReplyText('')
    clearDraft(selected.slot, selected.user_id)
    setAiSuggestion(null)
    const replyToId = replyToMessage
      ? Number(replyToMessage.id ?? replyToMessage.telegram_id)
      : null
    setReplyToMessage(null)
    try {
      const body = {
        user_id: selected.user_id,
        text,
        sent_by: suggestionActive ? 'ai_approved' : 'manual',
      }
      if (Number.isFinite(replyToId) && replyToId > 0) {
        body.reply_to_message_id = replyToId
      }
      if (replyChannel === 'whatsapp' && waStatus?.enabled) {
        body.channel = 'whatsapp'
      }
      const res = await fetch(`${API}/inbox/${encodeURIComponent(selected.slot)}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (data.status !== 'ok') {
        setError(data.message || 'Send failed')
        setMessages(prev => prev.map(m => (m.id === pendingId ? { ...m, status: 'failed' } : m)))
        return
      }
      if (data.message) {
        setMessages(prev => replacePendingMessage(prev, pendingId, data.message))
      }
      if (data.lead) {
        onCrmUpdate?.(null, data.lead)
      } else {
        const replyAt = data.message?.timestamp || new Date().toISOString()
        onCrmUpdate?.(null, {
          account_id: selected.slot,
          user_id: Number(selected.user_id),
          last_reply_at: replyAt,
          last_user_message_at:
            selectedConv?.crm_last_user_message_at
            ?? selectedConv?.last_user_message_at
            ?? null,
        })
      }
      onInboxPatchRef.current?.()
    } catch (e) {
      setError(String(e.message || e))
      setMessages(prev => prev.map(m => (m.id === pendingId ? { ...m, status: 'failed' } : m)))
    } finally {
      sendingRef.current = false
      setSending(false)
    }
  }

  async function sendMediaReply(file) {
    if (!selected || !file || sendingRef.current) return
    const caption = replyText.trim()
    const operatorLabel = (authUsername || 'Operator').trim()
    const mediaType = mediaTypeFromFile(file)
    const placeholder = OUTBOUND_MEDIA_LABELS[mediaType] || '[media]'
    const pendingId = `pending-media-${Date.now()}`
    const optimistic = {
      id: pendingId,
      chat_id: selected.user_id,
      account_id: selected.slot,
      direction: 'out',
      text: caption || placeholder,
      timestamp: new Date().toISOString(),
      status: 'sending',
      read_at: null,
      sent_by: 'manual',
      sender_name: operatorLabel,
      media: true,
      media_type: mediaType,
    }
    sendingRef.current = true
    setSending(true)
    setError('')
    stickToBottomRef.current = true
    forceScrollRef.current = true
    setShowNewMessages(false)
    setMessages(prev => [...prev, optimistic])
    setReplyText('')
    clearDraft(selected.slot, selected.user_id)
    setAiSuggestion(null)
    const replyToId = replyToMessage
      ? Number(replyToMessage.id ?? replyToMessage.telegram_id)
      : null
    setReplyToMessage(null)
    try {
      const form = new FormData()
      form.append('user_id', String(selected.user_id))
      form.append('file', file, file.name || 'upload')
      if (caption) form.append('caption', caption)
      if (Number.isFinite(replyToId) && replyToId > 0) {
        form.append('reply_to_message_id', String(replyToId))
      }
      const res = await fetch(
        `${API}/inbox/${encodeURIComponent(selected.slot)}/reply-media`,
        { method: 'POST', credentials: 'include', body: form },
      )
      const data = await res.json()
      if (data.status !== 'ok') {
        setError(data.message || 'Send failed')
        setMessages(prev => prev.map(m => (m.id === pendingId ? { ...m, status: 'failed' } : m)))
        return
      }
      if (data.message) {
        setMessages(prev => replacePendingMessage(prev, pendingId, data.message))
      }
      if (data.lead) {
        onCrmUpdate?.(null, data.lead)
      } else {
        const replyAt = data.message?.timestamp || new Date().toISOString()
        onCrmUpdate?.(null, {
          account_id: selected.slot,
          user_id: Number(selected.user_id),
          last_reply_at: replyAt,
          last_user_message_at:
            selectedConv?.crm_last_user_message_at
            ?? selectedConv?.last_user_message_at
            ?? null,
        })
      }
      onInboxPatchRef.current?.()
    } catch (e) {
      setError(String(e.message || e))
      setMessages(prev => prev.map(m => (m.id === pendingId ? { ...m, status: 'failed' } : m)))
    } finally {
      sendingRef.current = false
      setSending(false)
    }
  }

  const handleEditMessage = useCallback(async (messageId, text) => {
    if (!selected) return { ok: false, error: 'No chat selected' }
    const mid = Number(messageId)
    let prevText = ''
    setMessages(prev => prev.map(m => {
      if (Number(m.id) === mid && m.direction === 'out') {
        prevText = m.text || ''
        return { ...m, text, status: 'editing' }
      }
      return m
    }))
    try {
      const data = await patchInboxMessage(
        selected.slot,
        selected.user_id,
        mid,
        text,
      )
      if (data.status !== 'ok') {
        setMessages(prev => prev.map(m => (
          Number(m.id) === mid
            ? {
              ...m,
              text: prevText,
              status: m.status === 'editing' ? 'delivered' : m.status,
            }
            : m
        )))
        return { ok: false, error: data.message || 'Edit failed' }
      }
      const editedAt = data.message?.edited_at || new Date().toISOString()
      setMessages(prev => prev.map(m => {
        if (Number(m.id) === mid && m.direction === 'out') {
          return {
            ...m,
            text: data.message?.text ?? text,
            edited: true,
            edited_at: editedAt,
            status: m.status === 'editing'
              ? (data.message?.status || 'delivered')
              : m.status,
          }
        }
        return m
      }))
      setToast('Message edited')
      onInboxPatchRef.current?.()
      return { ok: true }
    } catch (e) {
      setMessages(prev => prev.map(m => (
        Number(m.id) === mid
          ? {
            ...m,
            text: prevText,
            status: m.status === 'editing' ? 'delivered' : m.status,
          }
          : m
      )))
      const err = String(e.message || e)
      return { ok: false, error: err }
    }
  }, [selected])

  const handleDeleteMessage = useCallback(async (messageId) => {
    if (!selected) return
    const ok = await confirm({
      title: 'Delete message?',
      message: 'This removes the message in Telegram for both sides. This cannot be undone.',
      variant: 'danger',
      confirmLabel: 'Delete',
    })
    if (!ok) return
    const mid = Number(messageId)
    try {
      const data = await deleteInboxMessage(
        selected.slot,
        selected.user_id,
        mid,
      )
      if (data.status !== 'ok') {
        setError(data.message || 'Delete failed')
        return
      }
      setMessages(prev => removeMessageById(prev, mid))
      setToast('Message deleted')
      onInboxPatchRef.current?.()
    } catch (e) {
      setError(String(e.message || e))
    }
  }, [selected, confirm])

  async function handleStatusChange(status) {
    if (!selected) return
    setCrmSaving(true)
    try {
      const data = await patchLead(selected.slot, selected.user_id, { status })
      onCrmUpdate?.(data.crm, data.lead)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setCrmSaving(false)
    }
  }

  async function handleSaveNotes() {
    if (!selected) return
    setCrmSaving(true)
    try {
      const data = await patchLead(selected.slot, selected.user_id, { notes })
      onCrmUpdate?.(data.crm, data.lead)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setCrmSaving(false)
    }
  }

  async function handleMarkHandled() {
    if (!selected) return
    setCrmSaving(true)
    try {
      const data = await markReplyHandled(selected.slot, selected.user_id)
      onCrmUpdate?.(data.crm, data.lead)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setCrmSaving(false)
    }
  }

  async function handleExportChat(format = 'txt') {
    if (!selected || exportingChat) return
    const { slot, user_id: userId } = selected
    setExportingChat(true)
    setError('')
    try {
      await downloadInboxChatExport(slot, userId, format)
      setToast(`Chat exported (${format})`)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setExportingChat(false)
    }
  }

  async function handleRefreshChat() {
    if (!selected || refreshingChat) return
    const { slot, user_id: userId } = selected
    setRefreshingChat(true)
    setError('')
    try {
      const syncRes = await fetch(
        `${API}/inbox/${encodeURIComponent(slot)}/sync/${userId}`,
        { method: 'POST' },
      )
      const syncData = await syncRes.json().catch(() => ({}))
      if (!syncRes.ok || syncData.status === 'error') {
        throw new Error(syncData.message || `Sync failed (${syncRes.status})`)
      }
      const msgRes = await fetch(
        `${API}/inbox/${encodeURIComponent(slot)}/messages/${userId}?sync=1`,
        { cache: 'no-store' },
      )
      if (!msgRes.ok) throw new Error(`HTTP ${msgRes.status}`)
      const data = await msgRes.json()
      if (data.status === 'ok' && Array.isArray(data.messages)) {
        setMessages(data.messages)
        setCanLoadOlderMessages(true)
        forceScrollRef.current = true
        stickToBottomRef.current = true
      }
      onInboxPatchRef.current?.()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setRefreshingChat(false)
    }
  }

  async function handleLoadOlderMessages() {
    if (!selected || loadingOlderMessages || !canLoadOlderMessages) return
    const beforeId = oldestTelegramMessageId(messages)
    if (beforeId == null) {
      setCanLoadOlderMessages(false)
      return
    }
    const { slot, user_id: userId } = selected
    const el = messagesScrollRef.current
    const prevHeight = el?.scrollHeight ?? 0
    const prevTop = el?.scrollTop ?? 0
    loadingOlderRef.current = true
    setLoadingOlderMessages(true)
    setError('')
    try {
      const res = await fetch(
        `${API}/inbox/${encodeURIComponent(slot)}/messages/${userId}/older?before_id=${beforeId}&limit=100`,
        { method: 'POST', cache: 'no-store' },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.status !== 'ok') {
        throw new Error(data.message || `Load failed (${res.status})`)
      }
      if (Array.isArray(data.messages)) {
        setMessages(data.messages)
      }
      if (!data.has_more || (data.added === 0 && data.fetched === 0)) {
        setCanLoadOlderMessages(false)
      }
      requestAnimationFrame(() => {
        const scrollEl = messagesScrollRef.current
        if (!scrollEl) return
        scrollEl.scrollTop = scrollEl.scrollHeight - prevHeight + prevTop
        stickToBottomRef.current = isUserNearBottom(scrollEl)
      })
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      loadingOlderRef.current = false
      setLoadingOlderMessages(false)
    }
  }

  async function handleAiSuggest() {
    if (!selected || aiSuggesting) return
    setAiSuggesting(true)
    setError('')
    try {
      const res = await fetch(
        `${API}/inbox/${encodeURIComponent(selected.slot)}/ai-suggestion`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: selected.user_id }),
        },
      )
      const data = await res.json()
      if (data.status !== 'ok') {
        throw new Error(data.message || data.error || 'AI suggestion failed')
      }
      const text = data.text || data.reply || ''
      if (!text.trim()) throw new Error('Empty suggestion from Karthik')
      setAiSuggestion({
        text,
        stage: data.stage,
        confidence: data.confidence,
      })
      setReplyText(text)
      saveDraft(selected.slot, selected.user_id, text)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setAiSuggesting(false)
    }
  }

  function handleDiscardAiSuggestion() {
    setAiSuggestion(null)
  }

  useEffect(() => {
    if (!selected) return undefined
    const t = window.setTimeout(() => {
      saveDraft(selected.slot, selected.user_id, replyText)
    }, 400)
    return () => clearTimeout(t)
  }, [replyText, selected?.slot, selected?.user_id])

  async function handleMarkSpam() {
    if (!selected) return
    setCrmSaving(true)
    setError('')
    try {
      const data = await karthikBlockChat(selected.slot, selected.user_id)
      onCrmUpdate?.(data.crm, data.lead)
      onInboxPatchRef.current?.()
      const label = selectedConv?.name || selectedConv?.username || 'Contact'
      setToast(`Karthik blocked ${label} — see Spam / Blocked filter`)
      closeConversation()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setCrmSaving(false)
    }
  }

  async function handleKarthikScanSpam() {
    setCrmSaving(true)
    setError('')
    try {
      const data = await karthikScanAndBlockSpam(
        mode === 'per_account' && filterSlot ? { slot: filterSlot } : {},
      )
      onCrmUpdate?.(data.crm)
      onInboxPatchRef.current?.()
      const n = Number(data.blocked_count) || 0
      setToast(
        n > 0
          ? `Karthik blocked ${n} spam chat${n === 1 ? '' : 's'}`
          : 'Karthik scan: no new spam chats found',
      )
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setCrmSaving(false)
    }
  }

  async function handleUnblock() {
    if (!selected) return
    setCrmSaving(true)
    try {
      const data = await unblockLead(selected.slot, selected.user_id)
      onCrmUpdate?.(data.crm, data.lead)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setCrmSaving(false)
    }
  }

  // Call-reminder ringing moved to GlobalNotificationSounds: a call falling due
  // must ring wherever the operator is, not only on the Inbox page.

  useEffect(() => {
    if (outcomeCall) return
    const past = crmState?.past_due_calls || []
    const next = past.find(
      c => c.id && !skippedOutcomeIdsRef.current.has(c.id),
    )
    if (next) setOutcomeCall(next)
  }, [crmState?.past_due_calls, outcomeCall])

  const openScheduleCallModal = useCallback(() => {
    unlockNotificationSound()
    setError('')
    setScheduleModalOpen(true)
  }, [])

  const liveCallContact = useMemo(() => {
    if (!selected) return null
    const lead = leadDetail || {}
    return {
      user_id: selected.user_id,
      account_id: selected.slot,
      name: lead.name || selectedConv?.name || '',
      username: lead.username || selectedConv?.username || '',
      phone: lead.phone || '',
    }
  }, [selected, leadDetail, selectedConv])

  const {
    outgoingCall,
    setOutgoingCall,
    startOutgoingCall,
    startWithMode,
    endOutgoingCall,
  } = useTelegramVoiceCall({
    selected,
    selectedConv,
    liveCallContact,
    onToast: setToast,
  })

  const beginOutgoingCall = useCallback(() => {
    unlockNotificationSound()
    setError('')
    setCallNowOpen(false)
    startOutgoingCall()
  }, [startOutgoingCall])

  useEffect(() => {
    if (!toast) return undefined
    const id = window.setTimeout(() => setToast(null), 3200)
    return () => clearTimeout(id)
  }, [toast])

  async function handleLiveCallSelect(option) {
    if (!selected || !option?.can_open) return
    setCallNowOpen(false)
    unlockNotificationSound()
    if (option.id === 'telegram') {
      await startOutgoingCall()
      return
    }
    if (option.id === 'whatsapp' || option.id === 'phone') {
      if (option.url) window.open(option.url, '_blank', 'noopener,noreferrer')
      return
    }
    await startWithMode('hybrid', { sendJoinDm: true })
  }

  async function handleScheduleCallConfirm(body) {
    if (!selected) return
    setCallScheduling(true)
    try {
      const data = await scheduleCall(selected.slot, selected.user_id, body)
      onCrmUpdate?.(data.crm, data.lead, data.call)
      if (data.call) {
        const sysMsg = {
          id: `sys-call-${data.call.id || Date.now()}`,
          direction: 'system',
          text: buildCallSystemMessage(data.call),
          timestamp: new Date().toISOString(),
        }
        setMessages(prev => [...prev, sysMsg])
        stickToBottomRef.current = true
        forceScrollRef.current = true
      }
      setScheduleModalOpen(false)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setCallScheduling(false)
    }
  }

  async function handleCallOutcome(status) {
    if (!outcomeCall) return
    setOutcomeSaving(true)
    try {
      const data = await completeCall(
        outcomeCall.account_id,
        outcomeCall.user_id,
        status,
      )
      onCrmUpdate?.(data.crm, data.lead, data.call)
      if (outcomeCall.id) skippedOutcomeIdsRef.current.add(outcomeCall.id)
      setOutcomeCall(null)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setOutcomeSaving(false)
    }
  }

  function handleDismissOutcome() {
    if (outcomeCall?.id) skippedOutcomeIdsRef.current.add(outcomeCall.id)
    setOutcomeCall(null)
  }

  function handleStartCall(call) {
    const link = buildCallLink(call)
    if (link.url) window.open(link.url, '_blank', 'noopener,noreferrer')
    else setError(link.label)
  }

  function handleOpenReminderCall(reminder) {
    const conv = conversations.find(
      c => c.account_id === reminder.account_id
        && Number(c.user_id) === Number(reminder.user_id),
    )
    if (conv) selectConversation(conv)
  }

  const handleLinkPhone = useCallback(async (phone) => {
    if (!selected || !phone?.trim()) return
    setLinkingPhone(true)
    setError('')
    try {
      const data = await linkLeadPhone(selected.slot, selected.user_id, phone.trim())
      if (data.conversation) {
        onInboxPatchRef.current?.()
      }
      setToast('Phone linked to this lead')
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLinkingPhone(false)
    }
  }, [selected])

  const handleMoveToWhatsApp = useCallback(async () => {
    if (!selected || sendingWa) return
    const name = selectedConv?.name || leadDetail?.name || 'there'
    const service = String(leadDetail?.notes || selectedConv?.crm_notes || 'interview support').slice(0, 40)
    setSendingWa(true)
    setError('')
    try {
      const data = await sendWhatsAppTemplate(
        selected.slot,
        selected.user_id,
        'whatsapp_move_from_telegram',
        [name, service],
      )
      if (data.message) {
        setMessages(prev => appendMessageDeduped(prev, data.message))
      }
      setReplyChannel('whatsapp')
      onInboxPatchRef.current?.()
      setToast('WhatsApp handoff message sent')
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setSendingWa(false)
    }
  }, [selected, sendingWa, selectedConv, leadDetail])

  const handleDemoToolsSent = useCallback(async (result) => {
    onInboxPatch?.()
    const sentAt = result?.sent_at
    if (sentAt && selected?.slot && selected?.user_id != null) {
      const key = `${selected.slot}:${selected.user_id}`
      const prev = crmState?.leads?.[key] || {}
      onCrmUpdate?.(null, { ...prev, demo_tools_sent_at: sentAt })
    }
    try {
      const crm = await fetchCrmState()
      onCrmUpdate?.(crm)
    } catch {
      /* CRM refresh optional */
    }
  }, [onInboxPatch, onCrmUpdate, selected, crmState?.leads])

  async function handleFollowUp(hours) {
    if (!selected) return
    setFollowUpLoading(true)
    try {
      const data = await scheduleFollowUp(selected.slot, selected.user_id, hours)
      onCrmUpdate?.(data.crm, data.lead)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setFollowUpLoading(false)
    }
  }

  function openDeleteChatModal() {
    if (!selected) return
    setDeleteChatError('')
    setDeleteChatOpen(true)
  }

  async function handleDeleteChatConfirm(password) {
    if (!selected) return
    const { slot, user_id: userId } = selected
    const label = selectedConv?.name || selectedConv?.username || String(userId)
    setDeleteChatLoading(true)
    setDeleteChatError('')
    try {
      await deleteInboxConversation(slot, userId, password)
      clearDraft(slot, userId)
      setDeleteChatOpen(false)
      closeConversation()
      setMessages([])
      setToast(`Cleared chat with ${label}`)
      onInboxPatch?.()
      try {
        const crm = await fetchCrmState()
        onCrmUpdate?.(crm)
      } catch {
        /* CRM refresh optional */
      }
    } catch (e) {
      setDeleteChatError(String(e.message || e))
    } finally {
      setDeleteChatLoading(false)
    }
  }

  const dueCount = crmState?.due_reminders?.length ?? 0
  const urgentBanner = formatUrgentTopBanner(alertCounts)

  const layoutClassName = [
    'crm-layout',
    'inbox-layout',
    'tg-inbox-shell',
    selected ? 'crm-layout--with-selected inbox-layout--with-selected' : '',
    leadDetailsOpen ? 'crm-layout--with-details' : '',
  ].filter(Boolean).join(' ')

  const rootClassName = [
    'inbox-root',
    'crm-root',
    'crm-root--compact-head',
    'tg-inbox-root',
    selected ? 'inbox-root--chat-open' : '',
  ].filter(Boolean).join(' ')

  return (
    <div className={rootClassName}>
      {urgentBanner && (
        <div className="crm-urgent-top-banner" role="alert">
          {urgentBanner}
        </div>
      )}

      {toast && (
        <div className="crm-toast" role="status" aria-live="polite">
          {toast}
        </div>
      )}

      <CallReminderBanner
        reminders={crmState?.call_reminders}
        onOpen={handleOpenReminderCall}
      />

      {leadDetailsOpen && (
        <button
          type="button"
          className="crm-lead-panel-backdrop"
          aria-label="Close lead details"
          onClick={() => setLeadDetailsOpen(false)}
        />
      )}

      <div className={layoutClassName}>
        <CRMInboxList
          conversations={conversations}
          selected={selected}
          mode={mode}
          filterSlot={filterSlot}
          accountSlots={accountSlots}
          accountInfo={accountInfo}
          onModeChange={setMode}
          onFilterSlotChange={setFilterSlot}
          filter={crmFilter}
          search={search}
          alertCounts={alertCounts}
          stats={crmState?.stats}
          dueCount={dueCount}
          onFilterChange={setCrmFilter}
          onSearchChange={setSearch}
          onSelect={selectConversation}
          onKarthikScanSpam={handleKarthikScanSpam}
          onBackToDashboard={onBackToDashboard}
        />
        <ChatWindow
          selected={selected}
          selectedConv={selectedConv}
          accountInfo={accountInfo}
          postingModes={postingModes}
          onBack={closeConversation}
          onBackToDashboard={onBackToDashboard}
          onOpenDetails={() => setLeadDetailsOpen(true)}
          onRefreshChat={handleRefreshChat}
          refreshingChat={refreshingChat}
          onLoadOlderMessages={handleLoadOlderMessages}
          loadingOlderMessages={loadingOlderMessages}
          canLoadOlderMessages={canLoadOlderMessages && messages.length > 0}
          messages={messages}
          loadingMessages={loadingMessages}
          replyText={replyText}
          onReplyChange={setReplyText}
          onSend={sendReply}
          onSendMedia={sendMediaReply}
          sending={sending}
          error={error}
          showNewMessages={showNewMessages}
          onJumpToLatest={jumpToLatest}
          messagesScrollRef={messagesScrollRef}
          onMessagesScroll={handleMessagesScroll}
          messagesEndRef={messagesEndRef}
          onQuickReply={text => setReplyText(text)}
          onScheduleCall={openScheduleCallModal}
          onCallNow={beginOutgoingCall}
          outgoingCall={outgoingCall}
          onOutgoingCallExpand={() => setOutgoingCall(o => o && { ...o, minimized: false })}
          onOutgoingCallMinimize={() => setOutgoingCall(o => o && { ...o, minimized: true })}
          onOutgoingCallEnd={() => endOutgoingCall('declined')}
          onOutgoingCallToggleMute={() => setOutgoingCall(o => o && { ...o, muted: !o.muted })}
          onMarkSpam={handleMarkSpam}
          onKarthikScanSpam={handleKarthikScanSpam}
          onMarkHandled={handleMarkHandled}
          onDeleteChat={openDeleteChatModal}
          onEditMessage={handleEditMessage}
          onDeleteMessage={handleDeleteMessage}
          replyToMessage={replyToMessage}
          onClearReply={() => setReplyToMessage(null)}
          onReplyToMessage={handleReplyToMessage}
          onForwardMessage={handleForwardMessage}
          onQuickReaction={handleQuickReaction}
          selectMode={selectMode}
          selectedMessageIds={selectedMessageIds}
          onToggleSelect={handleToggleSelect}
          onEnterSelectMode={handleEnterSelectMode}
          onExitSelectMode={handleExitSelectMode}
          onCopySelected={handleCopySelected}
          onDeleteSelected={handleDeleteSelected}
          onExportChat={handleExportChat}
          exportingChat={exportingChat}
          onAiSuggest={handleAiSuggest}
          aiSuggesting={aiSuggesting}
          aiSuggestion={aiSuggestion}
          onDiscardAiSuggestion={handleDiscardAiSuggestion}
          crmSaving={crmSaving}
          scheduledCall={selectedCall}
          whatsappEnabled={Boolean(waStatus?.enabled)}
          whatsappConfigured={Boolean(waStatus?.configured)}
          replyChannel={replyChannel}
          onReplyChannelChange={setReplyChannel}
          lead={leadDetail}
          onDemoToolsSent={handleDemoToolsSent}
        />
        <LeadDetailsPanel
          selected={selected}
          selectedConv={selectedConv}
          onClose={() => setLeadDetailsOpen(false)}
          scheduledCall={selectedCall}
          onScheduleCall={openScheduleCallModal}
          onStartCall={handleStartCall}
          onCallNow={beginOutgoingCall}
          outgoingCall={outgoingCall}
          onOutgoingCallExpand={() => setOutgoingCall(o => o && { ...o, minimized: false })}
          onOutgoingCallMinimize={() => setOutgoingCall(o => o && { ...o, minimized: true })}
          onOutgoingCallEnd={() => endOutgoingCall('declined')}
          onOutgoingCallToggleMute={() => setOutgoingCall(o => o && { ...o, muted: !o.muted })}
          onUnblock={handleUnblock}
          lead={leadDetail || (selectedConv ? {
            status: selectedConv.crm_status,
            crm_blocked: selectedConv.crm_blocked,
            notes: selectedConv.crm_notes,
            first_message_at: selectedConv.crm_first_message_at,
            last_reply_at: selectedConv.crm_last_reply_at,
            last_contact_time: selectedConv.crm_last_contact_time,
            reminder_timestamp: selectedConv.crm_reminder_timestamp,
            name: selectedConv.name,
            username: selectedConv.username,
            scheduled_call: selectedConv.crm_scheduled_call,
          } : null)}
          onStatusChange={handleStatusChange}
          notes={notes}
          onNotesChange={setNotes}
          onSaveNotes={handleSaveNotes}
          onFollowUp2h={() => handleFollowUp(2)}
          onFollowUpTomorrow={() => handleFollowUp(24)}
          onDeleteChat={openDeleteChatModal}
          saving={crmSaving}
          followUpLoading={followUpLoading}
          waStatus={waStatus}
          onLinkPhone={handleLinkPhone}
          onMoveToWhatsApp={handleMoveToWhatsApp}
          linking={linkingPhone}
          sendingWa={sendingWa}
        />
      </div>

      <OutgoingCallOverlay
        open={Boolean(outgoingCall && !outgoingCall.minimized)}
        name={outgoingCall?.name}
        seed={outgoingCall?.seed}
        channelLabel={outgoingCall?.channelLabel}
        status={outgoingCall?.status}
        muted={outgoingCall?.muted}
        error={outgoingCall?.error}
        durationSec={outgoingCall?.durationSec}
        onMinimize={() => setOutgoingCall(o => o && { ...o, minimized: true })}
        onDecline={() => endOutgoingCall('declined')}
        onDismiss={() => setOutgoingCall(null)}
        onToggleMute={() => setOutgoingCall(o => o && { ...o, muted: !o.muted })}
      />

      <CallNowModal
        open={callNowOpen}
        contact={liveCallContact}
        leadName={selectedConv?.name || selectedConv?.username}
        onSelect={handleLiveCallSelect}
        onClose={() => setCallNowOpen(false)}
        loading={false}
      />

      <ScheduleCallModal
        open={scheduleModalOpen}
        leadName={selectedConv?.name || selectedConv?.username}
        onConfirm={handleScheduleCallConfirm}
        onClose={() => setScheduleModalOpen(false)}
        saving={callScheduling}
      />

      <CallOutcomeModal
        open={Boolean(outcomeCall)}
        leadName={outcomeCall?.name || outcomeCall?.username}
        onSelect={handleCallOutcome}
        onDismiss={handleDismissOutcome}
        saving={outcomeSaving}
      />

      <DeleteChatModal
        open={deleteChatOpen}
        chatName={selectedConv?.name || selectedConv?.username}
        onCancel={() => {
          if (!deleteChatLoading) {
            setDeleteChatOpen(false)
            setDeleteChatError('')
          }
        }}
        onConfirm={handleDeleteChatConfirm}
        loading={deleteChatLoading}
        error={deleteChatError}
      />
    </div>
  )
}
