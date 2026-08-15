import React, { useEffect, useRef, useState } from 'react'
import { operationsUrl } from '../config.js'

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: '▣' },
  { id: 'accounts', label: 'Accounts', icon: '♙' },
  { id: 'forwarding', label: 'Forwarding', icon: '↻' },
  { id: 'campaigns', label: 'Campaigns', icon: '◉' },
  { id: 'inbox', label: 'Inbox & CRM', icon: '✉', badge: 'inbox' },
  { id: 'knowledge', label: 'Ask AI', icon: 'AI' },
  { id: 'logs', label: 'Logs', icon: '▤' },
  { id: 'admin', label: 'Admin', icon: '⚙' },
  { id: 'settings', label: 'Settings', icon: '◇' },
  { id: 'slot-booking', label: 'Slot booking', icon: '▦', external: true },
]

export function MessagingSidebar({ activeId, onNavigate, inboxUnreadTotal, connected, auth, mobileOpen }) {
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef(null)
  const displayName = auth.username || 'Administrator'
  const userInitials = displayName.slice(0, 2).toUpperCase()

  useEffect(() => {
    if (!userMenuOpen) return undefined
    const close = event => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target)) setUserMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [userMenuOpen])

  return (
    <aside className={`desktop-sidebar desktop-sidebar--sigma${mobileOpen ? ' desktop-sidebar--open' : ''}`}>
      <button type="button" className="desktop-sidebar__brand" onClick={() => onNavigate('accounts')} aria-label="Go to accounts">
        <span className="desktop-sidebar__logo" aria-hidden>⚡</span>
        <span className="desktop-sidebar__title">TeleAutomation</span>
      </button>
      <div className="messaging-sidebar__label">Messaging</div>
      <nav className="desktop-sidebar__nav" aria-label="Messaging navigation">
        {NAV.map(item => (
          <button
            key={item.id}
            type="button"
            className={`desktop-sidebar__link${activeId === item.id ? ' desktop-sidebar__link--active' : ''}`}
            onClick={() => item.external
              ? operationsUrl('/submit-slot') && window.open(operationsUrl('/submit-slot'), '_blank', 'noopener,noreferrer')
              : onNavigate(item.id)}
          >
            <span className="desktop-sidebar__link-icon" aria-hidden>{item.icon}</span>
            <span>{item.label}</span>
            {item.badge === 'inbox' && inboxUnreadTotal > 0 && (
              <span className="desktop-sidebar__badge">{inboxUnreadTotal > 99 ? '99+' : inboxUnreadTotal}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="desktop-sidebar__footer">
        <div className="desktop-sidebar__status">
          <span className="desktop-sidebar__status-check" aria-hidden>{connected ? '✓' : '…'}</span>
          {connected ? 'Messaging service online' : 'Reconnecting…'}
        </div>
        <div className="desktop-sidebar__uptime">
          <span>Independent Messaging workspace</span>
          <div className="desktop-sidebar__uptime-bar" aria-hidden><div className="desktop-sidebar__uptime-fill" style={{ width: connected ? '100%' : '35%' }} /></div>
        </div>
        <div className="desktop-sidebar__user-wrap" ref={userMenuRef}>
          <button type="button" className="desktop-sidebar__user" aria-expanded={userMenuOpen} onClick={() => setUserMenuOpen(open => !open)}>
            <span className="desktop-sidebar__user-avatar" aria-hidden>{userInitials}</span>
            <span className="desktop-sidebar__user-text">
              <span className="desktop-sidebar__user-name">{displayName}</span>
              <span className="desktop-sidebar__user-role">{auth.role || 'Administrator'}</span>
            </span>
            <span className="desktop-sidebar__user-chev" aria-hidden>▾</span>
          </button>
          {userMenuOpen && (
            <div className="desk-user-menu desk-user-menu--sidebar" role="menu">
              {auth.enabled ? (
                <button type="button" className="desk-user-menu__item desk-user-menu__item--danger" role="menuitem" onClick={auth.logout}>Sign out</button>
              ) : (
                <p className="desk-user-menu__hint">Login is not required on this server.</p>
              )}
              <button type="button" className="desk-user-menu__item" role="menuitem" onClick={() => { setUserMenuOpen(false); onNavigate('admin') }}>Admin</button>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
