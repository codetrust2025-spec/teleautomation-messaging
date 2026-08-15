import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AccountPanel } from './components/AccountPanel.jsx'
import { InboxPanel } from './components/InboxPanel.jsx'
import { KnowledgeAssistantPanel } from './components/KnowledgeAssistantPanel.jsx'
import { AdminPanel } from './components/AdminPanel.jsx'
import { LogPanel, LogsToolbarTabs } from './components/LogPanel.jsx'
import { MessagingSidebar } from './desktop/MessagingSidebar.jsx'
import { DesktopDashboardHome } from './desktop/DesktopDashboardHome.jsx'
import { aggregateFleetStats } from './utils/globalStats.js'
import { getLoggedInSlots } from './utils/accountUi.js'
import {
  WORKSPACE_CAMPAIGN,
  WORKSPACE_FLEET,
  WORKSPACE_FORWARDING,
} from './utils/workspaceMode.js'
import { useAuth } from './context/AuthContext.jsx'
import { GlobalNotificationSounds } from './notifications/GlobalNotificationSounds.jsx'
import { operationsUrl } from './config.js'

const EMPTY_STATE = {
  account_info: {},
  account_states: {},
  posting_modes: {},
  account_shutdown: {},
  shutdown_list: {},
}

const VIEW_TITLES = {
  dashboard: 'Dashboard',
  accounts: 'Accounts',
  forwarding: 'Forwarding',
  campaigns: 'Campaigns',
  inbox: 'Inbox & CRM',
  knowledge: 'Knowledge Assistant',
  logs: 'Logs',
  admin: 'Admin',
  settings: 'Settings',
}

async function api(path, options) {
  const response = await fetch(path, { credentials: 'include', ...options })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || body.message || `Request failed (${response.status})`)
  return body
}

function workspaceForView(view) {
  if (view === 'campaigns') return WORKSPACE_CAMPAIGN
  if (view === 'forwarding') return WORKSPACE_FORWARDING
  return WORKSPACE_FLEET
}

function modeForView(view) {
  if (view === 'campaigns') return 'campaign'
  if (view === 'forwarding') return 'forwarding'
  return 'all'
}

export default function App() {
  const auth = useAuth()
  const [view, setView] = useState('dashboard')
  const [state, setState] = useState(EMPTY_STATE)
  const [inbox, setInbox] = useState({ slots: {} })
  const [crm, setCrm] = useState({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [connected, setConnected] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [headerUserOpen, setHeaderUserOpen] = useState(false)
  const [logTab, setLogTab] = useState('logs')
  const [logScope, setLogScope] = useState('all')
  const [theme, setTheme] = useState('dark')
  const headerUserRef = useRef(null)
  const liveQueue = useRef([])
  const [liveTick, setLiveTick] = useState(0)

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      api('/state'),
      api('/inbox?sync=0'),
      api('/crm/state'),
    ])
    if (results[0].status === 'fulfilled') setState(results[0].value)
    if (results[1].status === 'fulfilled') setInbox(results[1].value)
    if (results[2].status === 'fulfilled') setCrm(results[2].value)
    const failure = results.find(item => item.status === 'rejected')
    setError(failure ? failure.reason.message : '')
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 15000)
    return () => clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${scheme}://${location.host}/ws`)
    socket.onopen = () => setConnected(true)
    socket.onclose = () => setConnected(false)
    socket.onerror = () => setConnected(false)
    socket.onmessage = event => {
      try {
        liveQueue.current.push(JSON.parse(event.data))
        setLiveTick(value => value + 1)
      } catch {}
    }
    return () => socket.close()
  }, [])

  useEffect(() => {
    if (!headerUserOpen) return undefined
    const close = event => {
      if (headerUserRef.current && !headerUserRef.current.contains(event.target)) {
        setHeaderUserOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [headerUserOpen])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  const act = async (key, path, options) => {
    setBusy(key)
    setError('')
    try {
      const result = await api(path, options)
      await refresh()
      return result
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setBusy('')
    }
  }

  const slots = state.account_slots || state.accounts || Object.keys(state.account_info || {})
  const subscriptionSlots = state.subscription_slots || []
  const accountInfo = state.account_info || {}
  const loggedInSlots = useMemo(() => getLoggedInSlots(slots, accountInfo), [slots, accountInfo])
  const activeAccount = state.active_account || slots.find(slot => accountInfo[slot]) || slots[0] || ''
  const inboxUnreadTotal = useMemo(() => (
    Object.values(inbox.slots || {}).reduce((total, block) => (
      total + (block.conversations || []).reduce((sum, row) => sum + Number(row.unread_count || 0), 0)
    ), 0)
  ), [inbox])
  const displayLogs = useMemo(() => (
    Object.entries(state.account_states || {}).flatMap(([slot, accountState]) => (
      (accountState.logs || []).map(entry => ({ ...entry, account_id: entry.account_id || slot }))
    ))
  ), [state.account_states])
  const displaySuccessList = state.success_list || []
  const displayFailedList = state.failed_list || []
  const fleet = useMemo(() => aggregateFleetStats(state, loggedInSlots, {
    postingModes: state.posting_modes || {},
    modeFilter: view === 'forwarding' ? 'forwarding' : view === 'campaigns' ? 'campaign' : 'all',
  }), [state, loggedInSlots, view])
  const anyRunning = fleet.runningCount > 0
  const displayName = auth.username || 'Administrator'
  const userInitials = displayName.slice(0, 2).toUpperCase()

  const navigate = nextView => {
    setView(nextView)
    setMobileNavOpen(false)
  }

  const provisionSlot = async () => {
    const result = await act('provision', '/accounts/provision-slot', { method: 'POST' })
    return result?.slot || ''
  }

  const accountPanel = (
    <AccountPanel
      state={state}
      configuredSlots={slots}
      subscriptionSlots={subscriptionSlots}
      accountsModeFilter={modeForView(view)}
      workspaceMode={workspaceForView(view)}
      onAccountsModeFilterChange={mode => navigate(mode === 'campaign' ? 'campaigns' : mode === 'forwarding' ? 'forwarding' : 'accounts')}
      onStartAccount={slot => act(`start:${slot}`, `/account/${slot}/start`, { method: 'POST' })}
      onStopAccount={slot => act(`stop:${slot}`, `/account/${slot}/stop`, { method: 'POST' })}
      onSwitchAccount={slot => act(`switch:${slot}`, '/account/switch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slot }),
      })}
      onRefreshJoined={slot => act(`refresh:${slot}`, '/account/refresh-joined', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slot }),
      })}
      refreshingJoinedSlot={busy.startsWith('refresh:') ? busy.split(':')[1] : ''}
      accountActionLoading={busy}
      switchingAccount={busy.startsWith('switch:') ? busy.split(':')[1] : null}
      onMessageSaved={refresh}
      onPostingModeUpdated={refresh}
      onShutdownUpdated={refresh}
      onRenamed={refresh}
      onProvisionSlot={provisionSlot}
      showShutdown={view === 'settings' || view === 'accounts'}
    />
  )

  let content = accountPanel
  let bodyClass = 'desktop-body messaging-body'
  if (view === 'dashboard') {
    content = (
      <DesktopDashboardHome
        state={state}
        loggedInSlots={loggedInSlots}
        postingModes={state.posting_modes || {}}
        inboxUnreadTotal={inboxUnreadTotal}
        fleet={fleet}
        globalCountdown={fleet.minCountdown || 0}
        sentWindowLabel={state.daily_stats?.window === 'since_reset' ? 'Since reset' : 'Last 24h'}
        activeSlot={activeAccount}
        activeRunning={Boolean(state.account_states?.[activeAccount]?.running)}
        anyProcessRunning={anyRunning}
        onSelectAccount={slot => act(`switch:${slot}`, '/account/switch', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slot }),
        })}
        onOpenSetup={() => navigate('accounts')}
        onOpenProgress={() => navigate('logs')}
        onResetReach={() => {
          if (window.confirm('Reset the displayed Messaging statistics?')) {
            act('reset', '/stats/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
          }
        }}
        onStartAccount={slot => act(`start:${slot}`, `/account/${slot}/start`, { method: 'POST' })}
        onStopAccount={slot => act(`stop:${slot}`, `/account/${slot}/stop`, { method: 'POST' })}
        accountActionLoading={busy}
        shutdownListCount={Object.keys(state.shutdown_list || {}).length}
        onNavBulk={() => navigate('campaigns')}
        onNavShutdown={() => navigate('settings')}
        onNavLogs={() => navigate('logs')}
        onNavData={() => operationsUrl('/') && window.open(operationsUrl('/'), '_blank', 'noopener,noreferrer')}
        onNavCandidates={() => operationsUrl('/') && window.open(operationsUrl('/'), '_blank', 'noopener,noreferrer')}
        onBookSlot={() => operationsUrl('/submit-slot') && window.open(operationsUrl('/submit-slot'), '_blank', 'noopener,noreferrer')}
        tickOverview={{}}
        recentLogs={displayLogs}
        workspaceMode={WORKSPACE_CAMPAIGN}
      />
    )
  } else if (view === 'inbox') {
    bodyClass += ' desktop-body--flush'
    content = (
      <InboxPanel
        inboxState={inbox}
        inboxLiveQueueRef={liveQueue}
        inboxLiveTick={liveTick}
        onInboxPatch={setInbox}
        accountSlots={slots}
        accountInfo={accountInfo}
        postingModes={state.posting_modes}
        crmState={crm}
        onCrmUpdate={setCrm}
        onBackToDashboard={() => navigate('accounts')}
      />
    )
  } else if (view === 'knowledge') {
    content = <KnowledgeAssistantPanel />
  } else if (view === 'admin') {
    content = <AdminPanel />
  } else if (view === 'logs') {
    bodyClass += ' desktop-body--flush'
    content = (
      <div className="logs-fullpage">
        <LogPanel
          activeTab={logTab}
          activeAccount={activeAccount}
          accountSlots={slots}
          logScope={logScope}
          onLogScopeChange={setLogScope}
          displayLogs={displayLogs}
          displaySuccessList={displaySuccessList}
          displayFailedList={displayFailedList}
          activeTabControl={(
            <LogsToolbarTabs
              activeTab={logTab}
              setActiveTab={setLogTab}
              logCount={displayLogs.length}
              okCount={displaySuccessList.length}
              failCount={displayFailedList.length}
            />
          )}
        />
      </div>
    )
  }

  return (
    <div className="desktop-app messaging-desktop-app">
      <GlobalNotificationSounds
        inboxState={inbox}
        inboxUnreadTotal={inboxUnreadTotal}
        crmState={crm}
      />
      <MessagingSidebar
        activeId={view}
        onNavigate={navigate}
        inboxUnreadTotal={inboxUnreadTotal}
        connected={connected}
        auth={auth}
        mobileOpen={mobileNavOpen}
      />

      {mobileNavOpen && (
        <button type="button" className="messaging-nav-backdrop" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />
      )}

      <div className="desktop-main">
        <header className="desktop-header desktop-header--sigma messaging-header">
          <button type="button" className="desktop-header__menu messaging-menu-button" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>☰</button>
          <div className="messaging-header__title-wrap">
            <p className="messaging-header__eyebrow">Messaging workspace</p>
            <h1 className="messaging-header__title">{VIEW_TITLES[view]}</h1>
          </div>
          <div className="desktop-header__status-center">
            <span className={`desktop-header__status-pulse${connected ? '' : ' desktop-header__status-pulse--warn'}`} aria-hidden />
            <span className="desktop-header__status-text">{connected ? 'Messaging service connected' : 'Reconnecting to Messaging service…'}</span>
          </div>
          <div className="desktop-header__actions messaging-header__runtime-actions">
            {anyRunning ? (
              <button type="button" className="desktop-header__bulk desktop-header__bulk--stop" disabled={busy === 'stop-all'} onClick={() => act('stop-all', '/stop', { method: 'POST' })}>■ Stop all</button>
            ) : (
              <button type="button" className="desktop-header__bulk desktop-header__bulk--start" disabled={!loggedInSlots.length || busy === 'start-all'} onClick={() => act('start-all', '/start', { method: 'POST' })}>▶ Start all</button>
            )}
            <button type="button" className="desktop-header__icon-btn desktop-header__icon-btn--util" title="Download joined groups CSV" onClick={() => window.open('/groups/total-list', '_blank', 'noopener,noreferrer')}><span aria-hidden>▤</span><span className="desktop-header__util-label">List</span></button>
            <button type="button" className="desktop-header__icon-btn" aria-label="Inbox notifications" onClick={() => navigate('inbox')}>🔔{inboxUnreadTotal > 0 && <span className="desktop-header__icon-badge">{inboxUnreadTotal > 99 ? '99+' : inboxUnreadTotal}</span>}</button>
            <button type="button" className="desktop-header__icon-btn desktop-header__theme-btn" aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`} onClick={() => setTheme(value => value === 'light' ? 'dark' : 'light')}><span aria-hidden>{theme === 'light' ? '☾' : '☀'}</span></button>
          </div>
          <div className="desktop-header__actions messaging-header__user-wrap" ref={headerUserRef}>
            <button type="button" className="desktop-header__user" aria-label="Open account menu" aria-expanded={headerUserOpen} onClick={() => setHeaderUserOpen(open => !open)}>{userInitials}</button>
            {headerUserOpen && (
              <div className="desk-user-menu messaging-header__user-menu" role="menu">
                <p className="desk-user-menu__label">Signed in as</p>
                <p className="desk-user-menu__name">{displayName}</p>
                {auth.enabled ? (
                  <button type="button" className="desk-user-menu__item desk-user-menu__item--danger" role="menuitem" onClick={auth.logout}>Sign out</button>
                ) : (
                  <p className="desk-user-menu__hint">Login is not required on this server.</p>
                )}
              </div>
            )}
          </div>
        </header>

        {error && <div role="alert" className="app-error messaging-app-error">{error} <button type="button" onClick={refresh}>Retry</button></div>}
        <main className={bodyClass}>{content}</main>
      </div>
    </div>
  )
}
