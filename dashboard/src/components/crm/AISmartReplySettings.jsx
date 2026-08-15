import React, { useEffect, useState } from 'react'
import { API } from '../../config.js'
import { ButtonContent } from '../../Loader.jsx'
import { useDialogA11y } from "../../hooks/useDialogA11y.js";

/**
 * Compact modal that lets the operator turn AI auto-reply on/off, swap the
 * model, edit the persona prompt, change the WhatsApp CTA link, and tune the
 * basic safety knobs (delay, daily caps). All settings persist to
 * `data/ai_smart_reply.json` so the next backend restart preserves them.
 * The API key itself lives in env vars (never round-tripped through the UI).
 */
export function AISmartReplySettings({ open, onClose, onChange }) {
  const dialogRef = useDialogA11y(open, onClose);
  const [config, setConfig] = useState(null)
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const res = await fetch(`${API}/ai/smart-reply/config`)
        const data = await res.json()
        if (cancelled) return
        if (data.status === 'ok') {
          setConfig(data.config)
          setHealth(data.health)
        } else {
          setError(data.message || 'Failed to load AI config')
        }
      } catch (e) {
        if (!cancelled) setError(String(e.message || e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [open])

  if (!open) return null

  const update = (patch) => setConfig((c) => ({ ...(c || {}), ...patch }))

  const save = async () => {
    if (!config) return
    setSaving(true)
    setError('')
    try {
      const res = await fetch(`${API}/ai/smart-reply/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setConfig(data.config)
        setHealth(data.health)
        onChange?.(data.config, data.health)
      } else {
        setError(data.message || 'Save failed')
      }
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setSaving(false)
    }
  }

  const apiKeyMissing = health && !health.api_key_present

  return (
    <div ref={dialogRef} className="ai-settings-overlay" role="dialog" aria-modal="true" aria-label="AI smart reply settings">
      <div className="ai-settings-card">
        <header className="ai-settings-header">
          <div>
            <div className="ai-settings-title">AI Smart Reply</div>
            <div className="ai-settings-sub">
              Auto-respond to inbound DMs and qualify leads toward WhatsApp.
            </div>
          </div>
          <button type="button" className="ai-settings-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        {loading && !config && <div className="empty-state">Loading…</div>}

        {config && (
          <div className="ai-settings-body">
            {apiKeyMissing && (
              <div className="ai-settings-warning" role="alert">
                <strong>API key missing.</strong>{' '}
                Set the <code>AI_API_KEY</code> (or <code>OPENAI_API_KEY</code>)
                environment variable on the backend, then restart the service.
              </div>
            )}

            <label className="ai-settings-row ai-settings-row--toggle">
              <span>
                <strong>Enable AI auto-reply</strong>
                <span className="ai-settings-row-hint">
                  When on, AI replies automatically to new DMs.
                </span>
              </span>
              <input
                type="checkbox"
                checked={!!config.enabled}
                onChange={(e) => update({ enabled: e.target.checked })}
              />
            </label>

            <label className="ai-settings-row">
              <span>Assistant name</span>
              <input
                type="text"
                value={config.assistant_name || ''}
                onChange={(e) => update({ assistant_name: e.target.value })}
                placeholder="Karthik"
                maxLength={32}
              />
            </label>

            <label className="ai-settings-row">
              <span>Model</span>
              <input
                type="text"
                value={config.model || ''}
                onChange={(e) => update({ model: e.target.value })}
                placeholder="gpt-4o-mini"
              />
            </label>

            <label className="ai-settings-row">
              <span>WhatsApp link (CTA)</span>
              <input
                type="text"
                value={config.whatsapp_link || ''}
                onChange={(e) => update({ whatsapp_link: e.target.value })}
                placeholder="https://wa.me/..."
              />
            </label>

            <label className="ai-settings-row ai-settings-row--full">
              <span>Business / persona prompt</span>
              <textarea
                rows={4}
                value={config.business_prompt || ''}
                onChange={(e) => update({ business_prompt: e.target.value })}
              />
            </label>

            <div className="ai-settings-grid">
              <label className="ai-settings-row">
                <span>Min reply delay (sec)</span>
                <input
                  type="number" min={0} max={300}
                  value={config.min_delay_seconds ?? 4}
                  onChange={(e) => update({ min_delay_seconds: Number(e.target.value) })}
                />
              </label>
              <label className="ai-settings-row">
                <span>Max reply delay (sec)</span>
                <input
                  type="number" min={0} max={300}
                  value={config.max_delay_seconds ?? 14}
                  onChange={(e) => update({ max_delay_seconds: Number(e.target.value) })}
                />
              </label>
              <label className="ai-settings-row">
                <span>Pause if human replied within (min)</span>
                <input
                  type="number" min={0} max={1440}
                  value={config.human_pause_minutes ?? 10}
                  onChange={(e) => update({ human_pause_minutes: Number(e.target.value) })}
                />
              </label>
              <label className="ai-settings-row">
                <span>Max AI replies per lead per day</span>
                <input
                  type="number" min={1} max={100}
                  value={config.max_replies_per_lead_per_day ?? 12}
                  onChange={(e) => update({ max_replies_per_lead_per_day: Number(e.target.value) })}
                />
              </label>
              <label className="ai-settings-row">
                <span>Max AI replies per account per hour</span>
                <input
                  type="number" min={1} max={500}
                  value={config.max_replies_per_account_per_hour ?? 30}
                  onChange={(e) => update({ max_replies_per_account_per_hour: Number(e.target.value) })}
                />
              </label>
              <label className="ai-settings-row">
                <span>Min confidence (0–1)</span>
                <input
                  type="number" step={0.05} min={0} max={1}
                  value={config.min_confidence ?? 0.45}
                  onChange={(e) => update({ min_confidence: Number(e.target.value) })}
                />
              </label>
            </div>

            {error && <div className="ai-settings-error" role="alert">{error}</div>}

            <footer className="ai-settings-footer">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={onClose}
                disabled={saving}
              >
                Close
              </button>
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={save}
                disabled={saving}
              >
                <ButtonContent loading={saving} loadingLabel="Saving…">Save settings</ButtonContent>
              </button>
            </footer>
          </div>
        )}
      </div>
    </div>
  )
}
