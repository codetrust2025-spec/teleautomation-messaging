import React, { useMemo, useState } from 'react'
import { API } from '../config.js'
import { Button } from './ui/Button.jsx'
import { ButtonContent, Spinner } from '../Loader.jsx'
import {
  accountLabel,
  formatDurationShort,
  formatPhoneDisplay,
  isAccountOnShutdown,
  telegramDisplayName,
} from '../utils/accountUi.js'
import { formatIstDateTime } from '../utils/istTime.js'

function shutdownReasonLabel(reason, lastSendAtIso) {
  const r = String(reason || 'no_post_6h')
  if (r.startsWith('no_post_ever_')) {
    const h = r.replace('no_post_ever_', '')
    return `Worker running but no successful post yet (idle ${h})`
  }
  if (r.startsWith('no_post_since_reset_')) {
    const h = r.replace('no_post_since_reset_', '')
    return `No successful posts since stats reset (idle ${h})`
  }
  if (r.startsWith('no_post_')) {
    const h = r.replace('no_post_', '')
    const last = lastSendAtIso
      ? ` · last success ${formatResume(lastSendAtIso)}`
      : ''
    return `No successful post for ${h}${last}`
  }
  return r.replace(/_/g, ' ')
}

function formatResume(iso) {
  return formatIstDateTime(iso)
}

export function ShutdownListPanel({
  shutdownList = {},
  accountShutdown = {},
  accountInfo = {},
  onUpdated,
  /** When true, always expanded (setup column Shutdown tab). */
  embedInTab = false,
  /** When > 0, show only this many rows + a "View all" button (dashboard preview). */
  previewLimit = 0,
  onViewAll = null,
}) {
  const [open, setOpen] = useState(embedInTab)
  const [clearing, setClearing] = useState(null)
  const [clearingAll, setClearingAll] = useState(false)
  const [error, setError] = useState(null)

  const rows = useMemo(() => {
    return Object.entries(shutdownList || {}).map(([slot, row]) => {
      const merged = { slot, ...row, ...(accountShutdown?.[slot] || {}) }
      const name =
        telegramDisplayName(accountInfo?.[slot]) || accountLabel(slot)
      const phone = accountInfo?.[slot]?.phone || ''
      return { ...merged, name, phone }
    })
  }, [shutdownList, accountShutdown, accountInfo])

  async function clearAll({ resetStats = false } = {}) {
    const slots = rows.map(r => r.slot).filter(Boolean)
    if (slots.length === 0) return
    setClearingAll(true)
    setError(null)
    try {
      for (const slot of slots) {
        const res = await fetch(`${API}/account/${slot}/shutdown/clear`, { method: 'POST' })
        const data = await res.json().catch(() => ({}))
        if (!res.ok || data.status === 'error') {
          throw new Error(data.message || data.error || `HTTP ${res.status}`)
        }
      }
      if (resetStats) {
        for (const slot of slots) {
          const res = await fetch(`${API}/stats/reset`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scope: 'account', account_id: slot }),
          })
          const data = await res.json().catch(() => ({}))
          if (!res.ok || data.status === 'error') {
            if (data.error !== 'reset_too_soon') {
              throw new Error(data.message || data.error || `Stats reset HTTP ${res.status}`)
            }
          }
        }
      }
      onUpdated?.()
    } catch (e) {
      setError(e.message || 'Could not clear shutdown list')
    } finally {
      setClearingAll(false)
    }
  }

  async function clearSlot(slot) {
    setClearing(slot)
    setError(null)
    try {
      const res = await fetch(`${API}/account/${slot}/shutdown/clear`, {
        method: 'POST',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.status === 'error') {
        throw new Error(data.message || `HTTP ${res.status}`)
      }
      onUpdated?.()
    } catch (e) {
      setError(e.message || 'Could not clear shutdown')
    } finally {
      setClearing(null)
    }
  }

  const sub = rows.length
    ? `${rows.length} account${rows.length !== 1 ? 's' : ''} resting`
    : 'Auto 1-week rest'

  const body = (
        <div id="shutdown-list-body" className="shutdown-list-body">
          <details className="shutdown-list-help-details">
            <summary className="shutdown-list-help-summary">Why accounts rest here (6h idle → 7 day pause)</summary>
            <p className="shutdown-list-help">
              Logged-in accounts with <strong>no successful posts for 6+ hours</strong>{' '}
              (campaign or forwarding) are stopped and rested here for{' '}
              <strong>7 days</strong>, then auto-restarted if they were running before.
              The 6h clock starts from your latest <strong>Start</strong> or last successful post.
              They are <strong>hidden from the Accounts grid</strong> while resting — use{' '}
              <strong>Clear</strong> or wait for auto-resume.
            </p>
          </details>
          {embedInTab && (
            <div className="shutdown-list-actions btn-row">
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={clearingAll || rows.length === 0}
                onClick={() => clearAll({ resetStats: false })}
              >
                <ButtonContent loading={clearingAll} loadingLabel="…">
                  Return all to campaign
                </ButtonContent>
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={clearingAll}
                onClick={() => clearAll({ resetStats: true })}
                title="Clear shutdown list and reset post counters so the 6h idle timer starts fresh"
              >
                <ButtonContent loading={clearingAll} loadingLabel="…">
                  Reset test cycle
                </ButtonContent>
              </Button>
            </div>
          )}
          {error && (
            <p className="shutdown-list-error" role="alert">
              {error}
            </p>
          )}
          {rows.length === 0 ? (
            <div className="shutdown-list-empty">
              <p>No accounts on shutdown list</p>
              <span className="shutdown-list-empty-sub">
                Accounts appear here after 6 hours with zero successful posts while
                campaign or forwarding is enabled.
              </span>
            </div>
          ) : (
            <ul className="shutdown-list-rows">
              {(previewLimit > 0 ? rows.slice(0, previewLimit) : rows).map(row => {
                const left = Number(row.seconds_until_resume) || 0
                const badge = isAccountOnShutdown(accountShutdown, row.slot)
                  ? `Resumes in ${formatDurationShort(left)}`
                  : 'Clearing…'
                return (
                  <li className="shutdown-list-row" key={row.slot}>
                    <div className="shutdown-list-row-main">
                      <span className="shutdown-list-row-name">{row.name}</span>
                      <span className="shutdown-list-row-slot">
                        {accountLabel(row.slot)}
                        {row.phone ? ` · ${formatPhoneDisplay(row.phone)}` : ''}
                      </span>
                    </div>
                    <div className="shutdown-list-row-meta">
                      <span className="shutdown-list-row-badge">{badge}</span>
                      <span
                        className="shutdown-list-row-resume"
                        title="Auto-restart time"
                      >
                        {formatResume(row.resume_at_iso)}
                      </span>
                    </div>
                    <p
                      className="shutdown-list-row-reason"
                      title="Why this account was auto-resting"
                    >
                      {shutdownReasonLabel(
                        row.reason,
                        row.last_send_at
                          ? new Date(Number(row.last_send_at) * 1000).toISOString()
                          : null,
                      )}
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shutdown-list-clear-btn"
                      disabled={clearing === row.slot}
                      onClick={() => clearSlot(row.slot)}
                      title="Remove from shutdown list and allow manual start"
                    >
                      <ButtonContent loading={clearing === row.slot} loadingLabel="…">
                        Clear
                      </ButtonContent>
                    </Button>
                  </li>
                )
              })}
            </ul>
          )}
          {previewLimit > 0 && rows.length > previewLimit && onViewAll && (
            <button
              type="button"
              className="shutdown-list-viewall"
              onClick={onViewAll}
            >
              View all {rows.length} resting →
            </button>
          )}
        </div>
  )

  if (embedInTab) {
    return (
      <section className="shutdown-list-panel shutdown-list-panel--tab shutdown-list-panel--open">
        <header className="shutdown-list-tab-head section-header section-header--compact">
          <h2 className="section-title">Shutdown list</h2>
          <span className="section-sub">{sub}</span>
          {rows.length > 0 && (
            <span className="shutdown-list-tab-head-count">{rows.length}</span>
          )}
        </header>
        {body}
      </section>
    )
  }

  return (
    <section className={`shutdown-list-panel${open ? ' shutdown-list-panel--open' : ''}`}>
      <button
        type="button"
        className="shutdown-list-toggle"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
        aria-controls="shutdown-list-body"
      >
        <span className="shutdown-list-toggle-main">
          <span className="shutdown-list-toggle-chevron" aria-hidden>
            {open ? '▾' : '▸'}
          </span>
          <span className="shutdown-list-toggle-title">Shutdown list</span>
          {rows.length > 0 && (
            <span className="shutdown-list-toggle-count">{rows.length}</span>
          )}
        </span>
        <span className="shutdown-list-toggle-sub">{sub}</span>
      </button>
      {open && body}
    </section>
  )
}

export function isSlotHiddenByShutdown(slot, accountShutdown, shutdownList) {
  return (
    isAccountOnShutdown(accountShutdown, slot)
    || !!(shutdownList && shutdownList[slot])
  )
}
