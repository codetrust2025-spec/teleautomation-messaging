import React, { useEffect, useState } from 'react'

import { CRM_FILTERS } from '../utils/crm.js'

import { formatAlertBanner } from '../utils/replyAlert.js'

import { accountLabel } from '../utils/accountUi.js'

import { CrmStatsBar } from '../components/crm/CrmStatsBar.jsx'

import { CrmBuzzerToggle } from '../components/crm/CrmBuzzerToggle.jsx'
import { WebPushToggle } from '../components/WebPushToggle.jsx'
import {
  enableWebPush,
  isWebPushEnabled,
  isWebPushSupported,
  notificationPermission,
} from '../utils/webPush.js'

const NOTIFY_BANNER_KEY = 'tg-inbox-notify-banner-dismissed'



export function InboxSidebarTools({

  mode,

  filterSlot,

  accountSlots,

  onModeChange,

  onFilterSlotChange,

  filter,

  search,

  onSearchChange,

  onFilterChange,

  alertCounts,

  stats,

  dueCount,

  menuOpen,

  onMenuOpenChange,

  onKarthikScanSpam,

  onBackToDashboard,

}) {

  const [notifyDismissed, setNotifyDismissed] = useState(true)
  const [pushBusy, setPushBusy] = useState(false)
  const [pushError, setPushError] = useState('')
  const pushSupported = isWebPushSupported()
  const pushActive = isWebPushEnabled() && notificationPermission() === 'granted'

  useEffect(() => {
    try {
      setNotifyDismissed(localStorage.getItem(NOTIFY_BANNER_KEY) === '1')
    } catch {
      setNotifyDismissed(false)
    }
  }, [])

  async function handleEnablePush() {
    setPushError('')
    setPushBusy(true)
    try {
      await enableWebPush()
      setNotifyDismissed(true)
      try {
        localStorage.setItem(NOTIFY_BANNER_KEY, '1')
      } catch {
        /* ignore */
      }
    } catch (e) {
      setPushError(e?.message || 'Could not enable notifications')
    } finally {
      setPushBusy(false)
    }
  }



  function dismissNotifyBanner() {

    setNotifyDismissed(true)

    try {

      localStorage.setItem(NOTIFY_BANNER_KEY, '1')

    } catch {

      /* ignore */

    }

  }



  return (

    <div className="tg-sidebar-sticky crm-inbox-list-tools">

      <div className="tg-sidebar-head">

        {typeof onBackToDashboard === 'function' && (

          <button

            type="button"

            className="tg-sidebar-dashboard-btn"

            onClick={onBackToDashboard}

            aria-label="Back to dashboard"

            title="Dashboard"

          >

            ←

          </button>

        )}

        <button

          type="button"

          className={`tg-sidebar-menu-btn${menuOpen ? ' tg-sidebar-menu-btn--open' : ''}`}

          onClick={() => onMenuOpenChange?.(!menuOpen)}

          aria-expanded={menuOpen}

          aria-label="Inbox options"

        >

          <span className="tg-sidebar-menu-icon" aria-hidden />

        </button>

        <div className="tg-sidebar-search-wrap">

          <span className="tg-sidebar-search-icon" aria-hidden="true">

            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">

              <circle cx="10.5" cy="10.5" r="6.5" stroke="currentColor" strokeWidth="2" />

              <path d="M15.5 15.5L20 20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />

            </svg>

          </span>

          <input

            type="text"

            inputMode="search"

            enterKeyHint="search"

            autoComplete="off"

            className="input crm-search-input tg-sidebar-search"

            placeholder="Search"

            value={search}

            onChange={e => onSearchChange(e.target.value)}

            aria-label="Search conversations"

          />

        </div>

      </div>



      {pushSupported && !pushActive && !notifyDismissed && (
        <div className="tg-sidebar-notify-banner" role="region" aria-label="Notifications">
          <button
            type="button"
            className="tg-sidebar-notify-close"
            onClick={dismissNotifyBanner}
            aria-label="Dismiss"
          >
            ×
          </button>
          <p className="tg-sidebar-notify-title">Never miss a message! 🔔</p>
          <p className="tg-sidebar-notify-sub">Get lock-screen alerts when a lead replies.</p>
          <button
            type="button"
            className="btn btn--sm btn--primary tg-sidebar-notify-enable"
            disabled={pushBusy}
            onClick={handleEnablePush}
          >
            {pushBusy ? 'Enabling…' : 'Enable notifications'}
          </button>
          {pushError && <p className="web-push-error">{pushError}</p>}
        </div>
      )}



      {menuOpen && (

        <div className="tg-sidebar-menu-panel" role="region" aria-label="Inbox filters">

          <div className="crm-inbox-list-modes tg-sidebar-modes">

            <button

              type="button"

              className={`chip chip--sm${mode === 'combined' ? ' chip--active' : ''}`}

              onClick={() => onModeChange?.('combined')}

            >

              Combined

            </button>

            <button

              type="button"

              className={`chip chip--sm${mode === 'per_account' ? ' chip--active' : ''}`}

              onClick={() => onModeChange?.('per_account')}

            >

              Per account

            </button>

            {mode === 'per_account' && accountSlots.length > 0 && (

              <select

                className="input input--select inbox-slot-select"

                value={filterSlot}

                onChange={e => onFilterSlotChange?.(e.target.value)}

                aria-label="Filter by account"

              >

                {accountSlots.map(s => (

                  <option key={s} value={s}>{accountLabel(s)}</option>

                ))}

              </select>

            )}

          </div>

          <div className="crm-filter-chips tg-sidebar-filters" role="tablist" aria-label="Lead filters">

            {CRM_FILTERS.map(f => (

              <button

                key={f.id}

                type="button"

                role="tab"

                aria-selected={filter === f.id}

                className={`chip chip--sm${filter === f.id ? ' chip--active' : ''}`}

                onClick={() => onFilterChange(f.id)}

              >

                {f.label}

              </button>

            ))}

          </div>

          <div className="crm-inbox-list-aux tg-sidebar-menu-aux">

            <CrmStatsBar stats={stats} dueCount={dueCount} alertCounts={alertCounts} compact />

            <CrmBuzzerToggle compact />
            <WebPushToggle compact />

            {typeof onKarthikScanSpam === 'function' && (
              <button
                type="button"
                className="btn btn--ghost btn--sm tg-karthik-spam-scan"
                onClick={() => {
                  onMenuOpenChange?.(false)
                  onKarthikScanSpam()
                }}
              >
                Karthik: block spam chats
              </button>
            )}

          </div>

        </div>

      )}



      {alertCounts?.total > 0 && (

        <p className="crm-delayed-banner tg-sidebar-notice" role="status">

          {formatAlertBanner(alertCounts)}

        </p>

      )}

    </div>

  )

}
