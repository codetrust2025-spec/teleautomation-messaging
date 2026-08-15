import React, { useCallback, useEffect, useState } from 'react'
import { API } from '../config.js'

async function fetchDemoToolsCatalog() {
  const res = await fetch(`${API}/demo-tools`, { credentials: 'include' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || data.status === 'error') {
    throw new Error(data.message || data.detail || 'Could not load demo tools')
  }
  return data
}

async function sendDemoTools(slot, userId) {
  const res = await fetch(`${API}/inbox/${encodeURIComponent(slot)}/send-demo-tools`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || data.status === 'error') {
    throw new Error(data.message || data.detail || 'Send failed')
  }
  return data
}

export function InboxDemoTools({ selected, lead, onSent, compact = false }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [catalog, setCatalog] = useState(null)

  const sentAt = lead?.graph?.demo_tools_sent_at || lead?.demo_tools_sent_at
  const hasLinks = (catalog?.tools || []).some(t => t.available)

  const loadCatalog = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setCatalog(await fetchDemoToolsCatalog())
    } catch (e) {
      setError(e.message || 'Load failed')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open && !catalog && !loading) loadCatalog()
  }, [open, catalog, loading, loadCatalog])

  async function handleSend() {
    if (!selected?.slot || selected.user_id == null) return
    setSending(true)
    setError('')
    try {
      const result = await sendDemoTools(selected.slot, selected.user_id)
      onSent?.(result)
      setOpen(false)
    } catch (e) {
      setError(e.message || 'Send failed')
    } finally {
      setSending(false)
    }
  }

  return (
    <>
      <button
        type="button"
        className={`demo-tools-btn${compact ? ' demo-tools-btn--compact' : ''}`}
        onClick={() => setOpen(true)}
        title="UltraViewer + LockedIn — Google Drive links"
      >
        🛠 Demo tools
      </button>
      {open && (
        <div className="demo-tools-modal-backdrop" onClick={() => setOpen(false)}>
          <div
            className="demo-tools-modal"
            role="dialog"
            aria-labelledby="demo-tools-title"
            onClick={e => e.stopPropagation()}
          >
            <div className="demo-tools-modal-header">
              <h3 id="demo-tools-title">Client demo tools</h3>
              <button
                type="button"
                className="demo-tools-modal-close"
                onClick={() => setOpen(false)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <p className="demo-tools-modal-lead">
              Sends <strong>Google Drive install links</strong> in Telegram: LockedIn (Windows + Mac) and
              UltraViewer. Karthik also auto-sends when demo time is confirmed.
            </p>
            {loading && <p className="demo-tools-hint">Loading…</p>}
            {error && <p className="demo-tools-error">{error}</p>}
            <ul className="demo-tools-list">
              {(catalog?.tools || []).map(tool => (
                <li className="demo-tools-item" key={tool.id}>
                  <div className="demo-tools-item-main">
                    <strong>{tool.name}</strong>
                    <p className="demo-tools-desc">{tool.description}</p>
                  </div>
                  {tool.client_url ? (
                    <a
                      className="btn btn--ghost btn--sm"
                      href={tool.client_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Open
                    </a>
                  ) : (
                    <span className="demo-tools-unavail">No link</span>
                  )}
                </li>
              ))}
            </ul>
            {selected?.slot && selected.user_id != null && (
              <div className="demo-tools-send-row">
                {sentAt && (
                  <span className="demo-tools-sent">
                    Sent{' '}
                    {new Date(sentAt).toLocaleString([], {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                )}
                <button
                  type="button"
                  className="btn btn--primary btn--sm"
                  disabled={sending || !hasLinks}
                  onClick={handleSend}
                >
                  {sending ? 'Sending…' : 'Send links to client'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
