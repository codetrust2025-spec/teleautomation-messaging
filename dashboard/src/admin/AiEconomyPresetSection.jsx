import React, { useCallback, useState } from 'react'
import { Spinner } from '../Loader.jsx'

/**
 * @param {object} props
 * @param {string} props.apiBase
 * @param {object|null} props.config
 * @param {(payload: object) => void} props.onConfigPatched
 * @param {(msg: string) => void} props.setError
 */
export function AiEconomyPresetSection({ apiBase, config, onConfigPatched, setError }) {
  const [busy, setBusy] = useState(false)
  const [replacePrompt, setReplacePrompt] = useState(true)

  const applyEconomy = useCallback(async () => {
    if (!window.confirm(
      'Apply Economy preset?\n\n'
      + '• Compact master prompt (shorter = lower API cost)\n'
      + '• 15 replies/lead/day, 12/account/hour, 8 history messages\n'
      + '• Group rewrite OFF\n'
      + '• Working hours 9am–9pm IST\n\n'
      + 'Teach Karthik entries are kept.',
    )) return
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${apiBase}/ai/smart-reply/preset/economy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ replace_business_prompt: replacePrompt }),
      })
      const data = await res.json()
      if (data.status !== 'ok') {
        setError(data.message || 'Economy preset failed')
        return
      }
      onConfigPatched(data)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }, [apiBase, onConfigPatched, replacePrompt, setError])

  const restoreStandardCaps = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`${apiBase}/ai/smart-reply/preset/standard-caps`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await res.json()
      if (data.status !== 'ok') {
        setError(data.message || 'Restore failed')
        return
      }
      onConfigPatched(data)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }, [apiBase, onConfigPatched, setError])

  const active = config?.budget_preset === 'economy'

  return (
    <section className="ai-economy-preset-card" aria-labelledby="ai-economy-preset-title">
      <div className="ai-economy-preset-head">
        <div>
          <h3 id="ai-economy-preset-title" className="ai-economy-preset-title">
            Budget: Economy preset
            {active && <span className="ai-economy-preset-badge">Active</span>}
          </h3>
          <p className="ai-economy-preset-hint">
            Cuts API cost (~$15–22/month target). Keeps auto-reply on gpt-4o-mini with tighter limits.
          </p>
        </div>
      </div>
      <ul className="ai-economy-preset-list">
        <li>15 AI replies per lead / day (was 25–30)</li>
        <li>12 replies per account / hour (was 30)</li>
        <li>8 messages of chat history (was 12–20)</li>
        <li>Group post rewrite off</li>
        <li>Working hours 9:00–21:00 IST</li>
        <li>Optional compact master prompt (much smaller = biggest saving)</li>
      </ul>
      <label className="ai-settings-row ai-settings-row--toggle ai-economy-preset-opt">
        <span>
          <strong>Use compact master prompt</strong>
          <span className="ai-settings-row-hint">
            Replaces the long business prompt with a short version. Your Teach Karthik entries stay.
          </span>
        </span>
        <input
          type="checkbox"
          checked={replacePrompt}
          onChange={e => setReplacePrompt(e.target.checked)}
          disabled={busy}
        />
      </label>
      <div className="ai-economy-preset-actions">
        <button
          type="button"
          className="btn btn--accent btn--sm"
          onClick={applyEconomy}
          disabled={busy}
        >
          {busy ? (
            <>
              <Spinner size={14} className="ui-spinner--on-dark" />
              <span>Applying…</span>
            </>
          ) : (
            'Apply Economy preset'
          )}
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={restoreStandardCaps}
          disabled={busy}
          title="Restore default caps only; does not change master prompt"
        >
          Restore standard caps
        </button>
      </div>
    </section>
  )
}
