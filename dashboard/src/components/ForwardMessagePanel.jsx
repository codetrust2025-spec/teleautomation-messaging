import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { API } from '../config.js'
import { ButtonContent } from '../Loader.jsx'
import { Button } from './ui/Button.jsx'
import { ProgressBar } from './ui/ProgressBar.jsx'
import { accountLabel, formatCountdown } from '../utils/accountUi.js'
import { formatIstDateTime } from '../utils/istTime.js'
import { forwardTmeUrlFromConfig } from '../utils/forwardAccountUtils.js'

const MAX_BATCH = 100

function groupKey(g) {
  return String(g.id ?? g.username ?? g.name)
}

function groupTitle(g) {
  const user = (g.username || '').trim()
  if (user) return user.startsWith('@') ? user : `@${user}`
  return (g.name || '').trim() || `id:${g.id}`
}

function formatIso(iso) {
  return formatIstDateTime(iso)
}

function etaCountdown(iso) {
  if (!iso) return null
  try {
    const sec = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 1000))
    return sec > 0 ? formatCountdown(sec) : 'soon'
  } catch {
    return null
  }
}

export function ForwardMessagePanel({
  slot,
  job: jobFromState,
  workerRunning = false,
  loggedIn = false,
  postingModeConfig,
}) {
  const fwd = postingModeConfig?.forwarding || {}
  const sourceType = fwd.source_type === 'telegram_post' ? 'telegram_post' : 'template'
  const sourceConfigured = !!fwd.configured
  const [preview, setPreview] = useState(null)
  const accountTmeUrl = useMemo(() => forwardTmeUrlFromConfig(fwd), [fwd])
  const [groups, setGroups] = useState([])
  const [selected, setSelected] = useState(() => new Set())
  const [savingSelection, setSavingSelection] = useState(false)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [loadingGroups, setLoadingGroups] = useState(false)
  const [sending, setSending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [dismissedJobId, setDismissedJobId] = useState(null)
  const [localJob, setLocalJob] = useState(null)
  const [groupsPartial, setGroupsPartial] = useState('')

  const mergedJob = useMemo(() => {
    const ws = jobFromState?.status && jobFromState.status !== 'idle' ? jobFromState : null
    const local = localJob?.status && localJob.status !== 'idle' ? localJob : null
    if (!ws && !local) return null
    if (!ws) return local
    if (!local) return ws
    if (ws.job_id === local.job_id) return ws
    const wsAt = ws.started_at || ws.started_at_iso || 0
    const localAt = local.started_at || local.started_at_iso || 0
    return localAt >= wsAt ? local : ws
  }, [jobFromState, localJob])

  const job = (
    mergedJob?.status
    && mergedJob.status !== 'idle'
    && mergedJob.job_id !== dismissedJobId
  ) ? mergedJob : null
  const running = job?.status === 'running'
  const done = job?.status === 'completed' || job?.status === 'failed' || job?.status === 'cancelled'
  const busy = running || loadingPreview || loadingGroups || sending || savingSelection
  const canSend = sourceConfigured && selected.size > 0 && !running
  const selectedIdsKey = useMemo(
    () => [...selected].sort((a, b) => Number(a) - Number(b)).join(','),
    [selected],
  )

  useEffect(() => {
    if (job?.preview) setPreview(job.preview)
  }, [job])

  useEffect(() => {
    if (!slot || !loggedIn) return
    setSelected(new Set())
    setGroups([])
    setPreview(null)
    setError('')
    let cancelled = false
    ;(async () => {
      try {
        const [selRes, grpRes] = await Promise.all([
          fetch(`${API}/account/${slot}/forward-cycle/selection`),
          fetch(`${API}/account/${slot}/forward-message/groups`),
        ])
        const selData = await selRes.json()
        const grpData = await grpRes.json()
        if (cancelled) return
        if (selData.status === 'ok' && Array.isArray(selData.target_ids)) {
          setSelected(new Set(selData.target_ids.filter(id => id != null)))
        }
        if (grpData.status === 'ok') {
          setGroups(grpData.groups || [])
          if (grpData.partial) {
            setGroupsPartial(
              grpData.partial_reason || 'Group list may be incomplete. Refresh to retry.',
            )
          }
        }
      } catch {
        /* ignore */
      }
    })()
    return () => { cancelled = true }
  }, [slot, loggedIn])

  useEffect(() => {
    if (!slot || selected.size === 0) return undefined
    const ids = [...selected]
    const timer = window.setTimeout(async () => {
      setSavingSelection(true)
      try {
        await fetch(`${API}/account/${slot}/forward-cycle/selection`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_ids: ids }),
        })
      } catch { /* ignore */ }
      finally {
        setSavingSelection(false)
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [slot, selectedIdsKey])

  useEffect(() => {
    if (!slot || !localJob?.job_id || localJob.status !== 'running') return undefined
    if (jobFromState?.job_id === localJob.job_id) return undefined
    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch(`${API}/account/${slot}/forward-message/job`)
        const data = await res.json()
        if (!cancelled && data.status === 'ok' && data.job) setLocalJob(data.job)
      } catch { /* ignore */ }
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [slot, localJob?.job_id, localJob?.status, jobFromState?.job_id])

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return groups
    return groups.filter(g => {
      const hay = `${g.name || ''} ${g.username || ''} ${g.type || ''}`.toLowerCase()
      return hay.includes(q)
    })
  }, [groups, search])

  const allSelected = filteredGroups.length > 0
    && filteredGroups.every(g => selected.has(g.id))

  const loadGroups = useCallback(async (forceRefresh = false) => {
    if (!slot) return
    setLoadingGroups(true)
    setError('')
    setGroupsPartial('')
    try {
      const qs = forceRefresh ? '?force_refresh=1' : ''
      const res = await fetch(`${API}/account/${slot}/forward-message/groups${qs}`)
      const data = await res.json()
      if (data.status === 'error') {
        setError(data.message || 'Could not load groups')
        return
      }
      setGroups(data.groups || [])
      if (data.partial) {
        setGroupsPartial(
          data.partial_reason || 'Group list may be incomplete (scan timed out). Refresh to retry.'
        )
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    } finally {
      setLoadingGroups(false)
    }
  }, [slot])

  async function loadPreview() {
    if (!slot || !accountTmeUrl.trim()) {
      setError('Save this account’s t.me link in Forwarding setup first')
      return
    }
    setLoadingPreview(true)
    setError('')
    try {
      const res = await fetch(`${API}/account/${slot}/forward-message/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url: accountTmeUrl.trim() }),
      })
      const data = await res.json()
      if (data.status === 'error') {
        setError(data.message || 'Could not load message')
        return
      }
      setPreview(data.job?.preview || null)
      if (!groups.length) await loadGroups()
    } catch (e) {
      setError(e.message || 'Request failed')
    } finally {
      setLoadingPreview(false)
    }
  }

  function toggleGroup(id) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAllVisible() {
    if (allSelected) {
      setSelected(prev => {
        const next = new Set(prev)
        filteredGroups.forEach(g => { if (g.id != null) next.delete(g.id) })
        return next
      })
    } else {
      setSelected(prev => {
        const next = new Set(prev)
        filteredGroups.forEach(g => { if (g.id != null) next.add(g.id) })
        return next
      })
    }
  }

  async function sendForward() {
    if (!slot || selected.size === 0) {
      setError('Select at least one group')
      return
    }
    if (!sourceConfigured) {
      setError(
        sourceType === 'telegram_post'
          ? 'Set a t.me post in Forwarding setup above first'
          : 'Set Message to send in Forwarding setup first',
      )
      return
    }
    setSending(true)
    setError('')
    try {
      const res = await fetch(`${API}/account/${slot}/forward-message/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_url: '',
          target_ids: [...selected],
          use_posting_mode_source: true,
          human_pace: true,
        }),
      })
      const data = await res.json()
      if (data.status === 'error') {
        setError(data.message || 'Could not start job')
        return
      }
      if (data.job) {
        setLocalJob(data.job)
        setDismissedJobId(null)
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    } finally {
      setSending(false)
    }
  }

  async function cancelJob() {
    if (!slot) return
    setCancelling(true)
    try {
      await fetch(`${API}/account/${slot}/forward-message/cancel`, { method: 'POST' })
    } catch { /* ignore */ }
    finally {
      setCancelling(false)
    }
  }

  async function resetForm() {
    const active = mergedJob
    if (active?.status === 'running') {
      await cancelJob()
    }
    if (active?.job_id) setDismissedJobId(active.job_id)
    setLocalJob(null)
    setPreview(null)
    setSelected(new Set())
    setSourceUrl('')
    setError('')
    setSearch('')
    setGroupsPartial('')
  }

  if (!slot) {
    return (
      <section className="forward-message-panel">
        <p className="stat-hint">Select an account to forward a message.</p>
      </section>
    )
  }

  if (!loggedIn) {
    return (
      <section className="forward-message-panel">
        <p className="stat-hint">Log in to {accountLabel(slot)} to use Smart Batch Forward.</p>
      </section>
    )
  }

  const live = job || {}
  const total = live.total_selected ?? selected.size
  const processed = live.total_processed ?? live.processed ?? 0
  const sent = live.sent ?? 0
  const failed = live.failed ?? 0
  const remaining = live.remaining ?? Math.max(0, total - processed)
  const percent = live.percent ?? (total > 0 ? Math.round((processed / total) * 100) : 0)
  const eta = etaCountdown(live.estimated_completion_iso)

  return (
    <section className="forward-message-panel">
      <header className="forward-message-panel__head">
        <h3 className="forward-message-panel__title">Forward cycle</h3>
        <span className="forward-message-panel__sub">
          Like Telegram: select groups, Send — one group at a time (2–6s between each)
        </span>
      </header>

      {!sourceConfigured && (
        <p className="forward-message-panel__warn">
          Set your message source in <strong>Forwarding setup</strong> above (template or t.me post).
        </p>
      )}

      {sourceType === 'telegram_post' && !running && !done && (
        <p className="stat-hint">
          {accountLabel(slot)} uses its own t.me post
          {accountTmeUrl ? (
            <>
              : <a href={accountTmeUrl} target="_blank" rel="noopener noreferrer">{accountTmeUrl}</a>
            </>
          ) : (
            <> — save a link in <strong>Forwarding setup</strong> above (not shared with other accounts).</>
          )}
        </p>
      )}

      {sourceType === 'template' && !running && !done && (
        <p className="stat-hint">
          {accountLabel(slot)} uses its own <strong>Message to send</strong> template (not shared).
        </p>
      )}

      {!running && !done && (
        <>
          <div className="btn-row forward-message-panel__actions">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => loadGroups(true)}
            >
              <ButtonContent loading={loadingGroups} loadingLabel="…">
                Refresh groups
              </ButtonContent>
            </Button>
          </div>

          {groupsPartial && (
            <p className="forward-message-panel__warn" role="status">
              {groupsPartial}
            </p>
          )}

          {preview && (
            <div className="forward-message-preview">
              <p className="forward-message-preview__label">Message preview</p>
              <p className="forward-message-preview__meta">
                {preview.label || preview.peer}
                {preview.date ? ` · ${formatIstDateTime(preview.date)} IST` : ''}
                {preview.has_media ? ' · media preserved on forward' : ''}
              </p>
              <p className="forward-message-preview__text">
                {preview.text_preview || preview.text || '(no text)'}
              </p>
            </div>
          )}

          {groups.length > 0 && (
            <div className="forward-message-groups">
              <div className="forward-message-groups__toolbar">
                <span className="forward-message-groups__count">
                  {selected.size} selected · {groups.length} joined
                </span>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={toggleAllVisible}
                  disabled={busy || filteredGroups.length === 0}
                >
                  {allSelected ? 'Clear visible' : 'Select visible'}
                </button>
              </div>
              <input
                className="input input--search"
                placeholder="Search groups…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                disabled={busy}
              />
              <div className="forward-message-groups__list" role="list">
                {filteredGroups.map(g => (
                  <label key={groupKey(g)} className="forward-message-groups__row" role="listitem">
                    <input
                      type="checkbox"
                      checked={selected.has(g.id)}
                      onChange={() => toggleGroup(g.id)}
                      disabled={busy || g.id == null}
                    />
                    <span className="forward-message-groups__name">{groupTitle(g)}</span>
                    <span className="forward-message-groups__type">{g.type || 'group'}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <Button
            type="button"
            variant="success"
            className="forward-message-panel__send"
            disabled={busy || !canSend}
            onClick={sendForward}
          >
            <ButtonContent loading={sending} loadingLabel="Sending…">
              Send to {selected.size} group{selected.size === 1 ? '' : 's'} (one at a time)
            </ButtonContent>
          </Button>
        </>
      )}

      {(running || done) && (
        <div className="forward-message-progress">
          <p className={`forward-message-progress__status forward-message-progress__status--${live.status}`}>
            {live.status === 'running' && 'Sending — one group at a time'}
            {live.status === 'completed' && 'Job completed'}
            {live.status === 'failed' && 'Job failed'}
            {live.status === 'cancelled' && 'Job cancelled'}
          </p>

          <div className="forward-message-dashboard">
            <div className="forward-message-dash-row">
              <span className="forward-message-dash-label">Job status</span>
              <span className="forward-message-dash-value">{live.status}</span>
            </div>
            <div className="forward-message-dash-row">
              <span className="forward-message-dash-label">Current batch</span>
              <span className="forward-message-dash-value">
                {live.current_batch || 0} / {live.total_batches || 0}
              </span>
            </div>
            <div className="forward-message-dash-row">
              <span className="forward-message-dash-label">Batch size</span>
              <span className="forward-message-dash-value">1 (human pace)</span>
            </div>
            {live.current_target && running && (
              <div className="forward-message-dash-row forward-message-dash-row--full">
                <span className="forward-message-dash-label">Current group</span>
                <span className="forward-message-dash-value">{live.current_target}</span>
              </div>
            )}
            <div className="forward-message-dash-row">
              <span className="forward-message-dash-label">Started</span>
              <span className="forward-message-dash-value">{formatIso(live.started_at_iso)}</span>
            </div>
            {running && live.estimated_completion_iso && (
              <div className="forward-message-dash-row">
                <span className="forward-message-dash-label">Est. completion</span>
                <span className="forward-message-dash-value">
                  {formatIso(live.estimated_completion_iso)}
                  {eta ? ` (~${eta})` : ''}
                </span>
              </div>
            )}
          </div>

          <div className="forward-message-stats forward-message-stats--wide">
            <div className="forward-message-stat">
              <span className="forward-message-stat__label">Selected</span>
              <span className="forward-message-stat__value">{total}</span>
            </div>
            <div className="forward-message-stat">
              <span className="forward-message-stat__label">Processed</span>
              <span className="forward-message-stat__value">{processed}</span>
            </div>
            <div className="forward-message-stat forward-message-stat--ok">
              <span className="forward-message-stat__label">Sent</span>
              <span className="forward-message-stat__value">{sent}</span>
            </div>
            <div className="forward-message-stat forward-message-stat--bad">
              <span className="forward-message-stat__label">Failed</span>
              <span className="forward-message-stat__value">{failed}</span>
            </div>
            <div className="forward-message-stat">
              <span className="forward-message-stat__label">Remaining</span>
              <span className="forward-message-stat__value">{remaining}</span>
            </div>
          </div>

          <ProgressBar value={percent} label={`${percent}% complete`} />

          {live.summary && (
            <p className="forward-message-progress__summary">{live.summary}</p>
          )}
          {live.error && <p className="field-error">{live.error}</p>}

          {live.attempt_logs?.length > 0 && (
            <details className="forward-message-log-details">
              <summary>Recent attempts ({live.attempt_logs.length})</summary>
              <ul className="forward-message-log-list">
                {live.attempt_logs.slice().reverse().map((row, i) => (
                  <li
                    key={`${row.ts}-${i}`}
                    className={`forward-message-log-item forward-message-log-item--${row.result}`}
                  >
                    <span className="forward-message-log-item__group">{row.group}</span>
                    <span className="forward-message-log-item__result">{row.result}</span>
                    {row.error_message && (
                      <span className="forward-message-log-item__err">{row.error_message}</span>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="btn-row">
            {running && (
              <Button
                type="button"
                variant="danger"
                size="sm"
                disabled={cancelling}
                onClick={cancelJob}
              >
                <ButtonContent loading={cancelling} loadingLabel="…">Cancel job</ButtonContent>
              </Button>
            )}
            {done && (
              <Button type="button" variant="ghost" size="sm" onClick={resetForm}>
                New forward job
              </Button>
            )}
          </div>
        </div>
      )}

      {error && <p className="field-error">{error}</p>}
    </section>
  )
}
