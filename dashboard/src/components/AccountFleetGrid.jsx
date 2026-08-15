import React, { useEffect, useMemo, useState } from 'react'
import { Spinner } from '../Loader.jsx'
import {
  accountLabel,
  formatAccountStatusLabel,
  formatJoinStatsToday,
  telegramDisplayName,
} from '../utils/accountUi'
import { SegmentedControl } from './ui/SegmentedControl.jsx'

const STATUS_TILE_LABELS = {
  running: 'Running',
  sleeping: 'Waiting',
  rate_limited: 'Flood',
  stopped: 'Stopped',
  idle: 'Offline',
}

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'sleeping', label: 'Sleeping' },
  { id: 'issues', label: 'Issues' },
]

function shortSlotLabel(slot) {
  return accountLabel(slot).replace('Account ', 'A')
}

function formatHealth(score) {
  const n = Number(score)
  if (score == null || Number.isNaN(n) || n <= 0) return null
  return `${Math.round(n)}%`
}

function lastActionText(row, acctState) {
  if (acctState?.running && acctState?.current_group) {
    return `Posting → @${String(acctState.current_group).replace(/^@/, '')}`
  }
  if (acctState?.notification) {
    const note = String(acctState.notification).trim()
    if (note) return note.length > 72 ? `${note.slice(0, 72)}…` : note
  }
  return formatAccountStatusLabel(row.status)
}

function buildTooltip(row, info, acctState) {
  const name = telegramDisplayName(info) || accountLabel(row.slot)
  const health = formatHealth(row.health) ?? '—'
  const joins = formatJoinStatsToday(acctState)
  const joinsStr = joins
    ? `${joins.today}${joins.limit != null ? `/${joins.limit}` : ''} joins today`
    : '—'
  return [
    name,
    `Health: ${health}`,
    `Last: ${lastActionText(row, acctState)}`,
    joinsStr,
  ].join('\n')
}

function matchesFilter(row, filter, acctState) {
  if (filter === 'all') return true
  if (filter === 'running') return row.status === 'running'
  if (filter === 'sleeping') return row.status === 'sleeping'
  if (filter === 'issues') {
    if (row.status === 'rate_limited') return true
    const h = Number(row.health)
    if (!Number.isNaN(h) && h > 0 && h < 40) return true
    if (acctState?.heavy_rate_limit) return true
  }
  return false
}

export function AccountFleetGrid({
  perAccount,
  accountInfo = {},
  accountStates = {},
  subscriptionSlots = [],
  activeAccount,
  onSelectAccount,
  switchingAccount,
  onAccountSelected,
}) {
  const [filter, setFilter] = useState('all')
  const [localSelected, setLocalSelected] = useState(activeAccount)
  const subs = Array.isArray(subscriptionSlots) ? subscriptionSlots : []

  useEffect(() => {
    setLocalSelected(activeAccount)
  }, [activeAccount])

  const rows = useMemo(
    () => perAccount.filter(row => matchesFilter(row, filter, accountStates[row.slot])),
    [perAccount, filter, accountStates],
  )

  if (!perAccount?.length) {
    return <p className="stat-hint">Log in to at least one account to see the grid.</p>
  }

  function handleSelect(slot) {
    setLocalSelected(slot)
    onAccountSelected?.(slot)
    onSelectAccount?.(slot)
  }

  const switching = switchingAccount != null

  return (
    <div className="acct-fleet-grid-wrap">
      <div className="acct-fleet-grid-header">
        <p className="acct-fleet-grid-lead" role="status" aria-live="polite">
          {switching
            ? `Switching to ${accountLabel(switchingAccount)}…`
            : 'Select an account to update the detail panel, logs, and metrics.'}
        </p>
        <SegmentedControl
          className="acct-fleet-filters"
          label="Filter accounts"
          options={FILTERS.map(f => ({ value: f.id, label: f.label }))}
          value={filter}
          onChange={setFilter}
        />
      </div>

      <div className="acct-fleet-grid" role="listbox" aria-label="Account selector">
        {rows.length === 0 ? (
          <p className="stat-hint acct-fleet-grid-empty">No accounts match this filter.</p>
        ) : (
          rows.map(row => {
            const info = accountInfo[row.slot]
            const acctState = accountStates[row.slot]
            const isSub = subs.includes(row.slot)
            const selected = (localSelected || activeAccount) === row.slot
            const health = formatHealth(row.health)
            const statusLabel = STATUS_TILE_LABELS[row.status] || STATUS_TILE_LABELS.stopped
            const busy = switchingAccount === row.slot

            return (
              <button
                key={row.slot}
                type="button"
                role="option"
                aria-selected={selected}
                className={[
                  'acct-fleet-tile',
                  `acct-fleet-tile--${row.status}`,
                  isSub ? 'acct-fleet-tile--subscription' : '',
                  selected ? 'acct-fleet-tile--selected' : '',
                  busy ? 'acct-fleet-tile--busy' : '',
                ].filter(Boolean).join(' ')}
                title={buildTooltip(row, info, acctState)}
                onClick={() => handleSelect(row.slot)}
              >
                <span className="acct-fleet-tile-top">
                  <span className="acct-fleet-tile-id">{shortSlotLabel(row.slot)}</span>
                  {isSub && <span className="acct-fleet-tile-sub" aria-hidden title="Subscription">◆</span>}
                </span>
                <span className="acct-fleet-tile-status-row">
                  <span className="acct-fleet-tile-dot" aria-hidden />
                  <span className="acct-fleet-tile-status">{statusLabel}</span>
                </span>
                {health && (
                  <span className="acct-fleet-tile-health">{health}</span>
                )}
                {busy && (
                  <span className="acct-fleet-tile-switching" aria-hidden>
                    <Spinner size={16} />
                  </span>
                )}
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
