import React, { useCallback, useEffect, useState } from 'react'
import { API } from '../config.js'
import { Button } from './ui/Button.jsx'
import { ButtonContent } from '../Loader.jsx'
import { useConfirm } from '../context/ConfirmContext.jsx'
import { WORKSPACE_CAMPAIGN, WORKSPACE_FORWARDING } from '../utils/workspaceMode.js'
import { SABHI_ACCOUNTS, SABHI_SETUP } from '../utils/sabAccountsUi.js'

async function parseApiJson(res) {
  const text = await res.text()
  if (!text.trim()) {
    return { _parseError: res.ok ? 'Empty response' : `HTTP ${res.status}` }
  }
  try {
    return JSON.parse(text)
  } catch {
    const snippet = text.replace(/\s+/g, ' ').slice(0, 80)
    const hint = snippet.startsWith('<') ? ' (server returned HTML — try hard refresh)' : ''
    return {
      _parseError: `Invalid response (${res.status})${hint}`,
      _raw: snippet,
    }
  }
}

function apiError(data, fallback) {
  if (data?._parseError) return data._parseError
  return data?.message || data?.detail || data?.error || fallback
}

function summarizeBulkResult(data) {
  const n = data?.updated?.length ?? 0
  const run = data?.skipped_running?.length ?? 0
  const err = Object.keys(data?.errors || {}).length
  const parts = [`${n} account${n !== 1 ? 's' : ''} set to Forwarding + link`]
  if (run) parts.push(`${run} skipped (stop running accounts first)`)
  if (err) parts.push(`${err} errors`)
  return parts.join(' · ')
}

function summarizeLinkOnlyResult(data) {
  const n = data?.updated?.length ?? 0
  const run = data?.skipped_running?.length ?? 0
  const mode = data?.skipped_mode?.length ?? 0
  const err = Object.keys(data?.errors || {}).length
  const parts = [`${n} link${n !== 1 ? 's' : ''} saved`]
  if (mode) {
    parts.push(
      `${mode} skipped (still on Campaign — use the blue “All → Forwarding + link” button)`,
    )
  }
  if (run) parts.push(`${run} skipped (running — stop first)`)
  if (err) parts.push(`${err} errors`)
  return parts.join(' · ')
}

/**
 * All-accounts defaults: shared t.me link or campaign message applied to every logged-in account.
 */
export function FleetDefaultsPanel({
  workspaceMode = WORKSPACE_FORWARDING,
  loggedInCount = 0,
  onUpdated,
  embedInTab = false,
}) {
  const confirm = useConfirm()
  const [forwardUrl, setForwardUrl] = useState('')
  const [campaignMessage, setCampaignMessage] = useState('')
  const [loading, setLoading] = useState(null)
  const [error, setError] = useState('')
  const [lastResult, setLastResult] = useState('')

  const loadDefaults = useCallback(async () => {
    try {
      const res = await fetch(`${API}/fleet/defaults`, { credentials: 'include' })
      const data = await parseApiJson(res)
      if (data._parseError) return
      if (data.forward_source_url) setForwardUrl(data.forward_source_url)
      if (data.campaign_message) setCampaignMessage(data.campaign_message)
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    loadDefaults()
  }, [loadDefaults])

  async function saveDefaults() {
    setLoading('save')
    setError('')
    try {
      const body =
        workspaceMode === WORKSPACE_FORWARDING
          ? { forward_source_url: forwardUrl.trim() }
          : { campaign_message: campaignMessage.trim() }
      const res = await fetch(`${API}/fleet/defaults`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const data = await parseApiJson(res)
      if (data._parseError || !res.ok) throw new Error(apiError(data, 'Save failed'))
      if (data.status === 'error') throw new Error(apiError(data, 'Save failed'))
      setLastResult('Default saved')
      onUpdated?.()
    } catch (e) {
      setError(e.message || 'Could not save default')
    } finally {
      setLoading(null)
    }
  }

  async function applyAll(kind) {
    const isForward = kind === 'forwarding'
    const label = isForward ? 'Forwarding (24/7 + t.me link)' : 'Campaign'
    const ok = await confirm({
      title: `Apply ${label} to ${SABHI_ACCOUNTS.toLowerCase()}?`,
      message: `This updates every logged-in account (${loggedInCount || 'all'}). Running accounts are skipped — stop them first. Continue?`,
      confirmLabel: 'Apply to all',
      variant: 'warn',
    })
    if (!ok) return

    setLoading(kind)
    setError('')
    setLastResult('')
    try {
      if (forwardUrl.trim() && isForward) {
        await fetch(`${API}/fleet/defaults`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ forward_source_url: forwardUrl.trim() }),
        })
      }
      if (campaignMessage.trim() && !isForward) {
        await fetch(`${API}/fleet/defaults`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ campaign_message: campaignMessage.trim() }),
        })
      }

      const path = isForward ? '/fleet/apply-forwarding' : '/fleet/apply-campaign'
      const body = isForward
        ? {
            source_url: forwardUrl.trim() || undefined,
            use_saved_default: !forwardUrl.trim(),
            forward_dispatch: 'auto',
          }
        : {
            message: campaignMessage.trim() || undefined,
            use_saved_default: !campaignMessage.trim(),
          }

      const res = await fetch(`${API}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const data = await parseApiJson(res)
      if (data._parseError || !res.ok) throw new Error(apiError(data, 'Apply failed'))
      if (data.status === 'error') throw new Error(apiError(data, 'Apply failed'))
      setLastResult(summarizeBulkResult(data))
      onUpdated?.()
    } catch (e) {
      setError(e.message || 'Apply failed')
    } finally {
      setLoading(null)
    }
  }

  async function applyLinkOnly() {
    if (!forwardUrl.trim()) {
      setError('Paste a default t.me post link first')
      return
    }
    setLoading('link')
    setError('')
    try {
      await fetch(`${API}/fleet/defaults`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ forward_source_url: forwardUrl.trim() }),
      })
      const res = await fetch(`${API}/fleet/apply-source-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ source_url: forwardUrl.trim() }),
      })
      const data = await parseApiJson(res)
      if (data._parseError || !res.ok) throw new Error(apiError(data, 'Apply failed'))
      if (data.status === 'error') throw new Error(apiError(data, 'Apply failed'))
      setLastResult(summarizeLinkOnlyResult(data))
      onUpdated?.()
    } catch (e) {
      setError(e.message || 'Could not apply link')
    } finally {
      setLoading(null)
    }
  }

  const isForward = workspaceMode === WORKSPACE_FORWARDING

  return (
    <section
      className={`fleet-defaults-panel${embedInTab ? ' fleet-defaults-panel--tab' : ''}`}
      aria-label={`${SABHI_SETUP} — all logged-in accounts`}
      >
      <header className="fleet-defaults-panel__head">
        <h3 className="fleet-defaults-panel__title">{SABHI_SETUP}</h3>
        <p className="stat-hint fleet-defaults-panel__hint">
          Same link or message for <strong>all</strong> logged-in accounts at once — different from picking one card on{' '}
          <strong>Each account</strong>.
          {loggedInCount > 0 ? ` ${loggedInCount} logged in.` : ''}
        </p>
      </header>

      {isForward ? (
        <div className="fleet-defaults-panel__block">
          <label className="fleet-defaults-panel__label">
            Default t.me post link
            <input
              type="url"
              className="input"
              placeholder="https://t.me/yourchannel/123"
              value={forwardUrl}
              onChange={e => setForwardUrl(e.target.value)}
            />
          </label>
          <div className="fleet-defaults-panel__actions btn-row">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!!loading}
              onClick={saveDefaults}
            >
              <ButtonContent loading={loading === 'save'} loadingLabel="…">Save default</ButtonContent>
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={!!loading}
              onClick={() => applyAll('forwarding')}
              title="Every logged-in account: switch to Forwarding, 24/7 auto, and this t.me link"
            >
              <ButtonContent loading={loading === 'forwarding'} loadingLabel="…">
                All → Forwarding + link
              </ButtonContent>
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!!loading || !forwardUrl.trim()}
              onClick={applyLinkOnly}
              title="Does not switch Campaign accounts — only copies the link to accounts already on Forwarding"
            >
              <ButtonContent loading={loading === 'link'} loadingLabel="…">
                Link only (forwarding already)
              </ButtonContent>
            </Button>
          </div>
        </div>
      ) : (
        <div className="fleet-defaults-panel__block">
          <label className="fleet-defaults-panel__label">
            Default campaign message
            <textarea
              className="input input--textarea"
              rows={4}
              placeholder="Shared template for campaign posts…"
              value={campaignMessage}
              onChange={e => setCampaignMessage(e.target.value)}
            />
          </label>
          <div className="fleet-defaults-panel__actions btn-row">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!!loading}
              onClick={saveDefaults}
            >
              <ButtonContent loading={loading === 'save'} loadingLabel="…">Save default</ButtonContent>
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={!!loading}
              onClick={() => applyAll('campaign')}
              title="Enable Campaign + copy message to every logged-in account"
            >
              <ButtonContent loading={loading === 'campaign'} loadingLabel="…">
                All → Campaign + message
              </ButtonContent>
            </Button>
          </div>
        </div>
      )}

      {error && (
        <p className="fleet-defaults-panel__error" role="alert">{error}</p>
      )}
      {lastResult && !error && (
        <p className="fleet-defaults-panel__ok" role="status">{lastResult}</p>
      )}
    </section>
  )
}
