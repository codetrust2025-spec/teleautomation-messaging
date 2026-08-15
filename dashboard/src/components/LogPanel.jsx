import React, { useMemo, useState } from 'react'
import { formatLogEventLabel, formatLogTime } from '../utils/accountUi'
import { SABHI_ACCOUNTS } from '../utils/sabAccountsUi.js'
import { Button } from './ui/Button.jsx'
import { SegmentedControl } from './ui/SegmentedControl.jsx'

const LOG_LEVEL_ICON = {
  success: '●',
  error: '●',
  warning: '●',
  info: '○',
}

function LogLine({ entry }) {
  const level = entry.level || 'info'
  const icon = LOG_LEVEL_ICON[level] || LOG_LEVEL_ICON.info
  const event = entry.event || ''
  const msg = entry.msg || ''
  return (
    <div className={`log-line log-line--${level}`}>
      <span className="log-line-icon" aria-hidden>{icon}</span>
      <time className="log-line-time">{formatLogTime(entry.time)}</time>
      {event && (
        <span className="log-line-event" title={event}>
          {formatLogEventLabel(event)}
        </span>
      )}
      <span className="log-line-msg">{msg}</span>
    </div>
  )
}

function isCycleBoundary(entry) {
  const event = (entry.event || '').toUpperCase()
  if (event === 'CYCLE_START' || event === 'CYCLE_RESUME') return true
  const action = (entry.action || '').toLowerCase()
  const msg = (entry.msg || '').toLowerCase()
  return action === 'cycle_start' || msg.includes('cycle_start') || msg.includes('--- cycle')
}

export function LogsToolbarTabs({ activeTab, setActiveTab, logCount, okCount, failCount }) {
  const options = [
    { value: 'logs', label: `Logs (${logCount})` },
    { value: 'success', label: `OK (${okCount})` },
    { value: 'failed', label: `Fail (${failCount})` },
  ]
  return (
    <SegmentedControl
      className="logs-toolbar-tabs"
      label="Log tabs"
      options={options}
      value={activeTab}
      onChange={setActiveTab}
    />
  )
}

export function LogPanel({
  activeTab,
  activeAccount,
  accountSlots,
  logScope,
  onLogScopeChange,
  displayLogs,
  displaySuccessList,
  displayFailedList,
  logsContainerRef,
  onScroll,
  toolbarActions,
  activeTabControl,
}) {
  const [levelFilter, setLevelFilter] = useState('all') // all | errors | account
  const [groupByCycle, setGroupByCycle] = useState(false)

  const logsNewestFirst = useMemo(() => [...displayLogs].reverse(), [displayLogs])
  const successNewestFirst = useMemo(() => [...displaySuccessList].reverse(), [displaySuccessList])
  const failedNewestFirst = useMemo(() => [...displayFailedList].reverse(), [displayFailedList])

  const filteredLogs = useMemo(() => {
    let list = logsNewestFirst
    if (levelFilter === 'errors') list = list.filter(e => e.level === 'error')
    return list
  }, [logsNewestFirst, levelFilter])

  const logGroups = useMemo(() => {
    if (!groupByCycle) return null
    const groups = []
    let current = { id: 0, label: 'Recent', entries: [] }
    for (const entry of filteredLogs) {
      if (isCycleBoundary(entry)) {
        if (current.entries.length) groups.push(current)
        const m = (entry.cycle != null ? String(entry.cycle) : (entry.msg || '').match(/cycle=(\d+)/i)?.[1])
        current = { id: groups.length, label: m ? `Cycle ${m}` : 'Cycle', entries: [entry] }
      } else {
        current.entries.push(entry)
      }
    }
    if (current.entries.length) groups.push(current)
    return groups.length ? groups : null
  }, [filteredLogs, groupByCycle])

  return (
    <div className="log-panel-root">
      <div className="logs-toolbar-row logs-toolbar-row--filters">
        {toolbarActions}
        {activeTabControl}
      </div>
      {activeTab === 'logs' && (
        <div className="logs-filters">
          <div className="logs-filter-chips">
            <SegmentedControl
              label="Log scope"
              options={[
                { value: 'account', label: activeAccount || 'Account' },
                { value: 'all', label: SABHI_ACCOUNTS },
              ]}
              value={logScope}
              onChange={onLogScopeChange}
            />
            {logScope === 'all' ? (
              <span className="logs-account-chip" title="Logs from every account">
                {SABHI_ACCOUNTS} ({accountSlots?.length || 0})
              </span>
            ) : activeAccount && (
              <span className="logs-account-chip" title="Logs scoped to selected account">
                {activeAccount}
              </span>
            )}
            <SegmentedControl
              label="Filter logs"
              options={[
                { value: 'all', label: 'All levels' },
                { value: 'errors', label: 'Errors only' },
              ]}
              value={levelFilter}
              onChange={setLevelFilter}
            />
          </div>
          <label className="logs-filter-toggle">
            <input type="checkbox" checked={groupByCycle} onChange={e => setGroupByCycle(e.target.checked)} />
            Group by cycle
          </label>
        </div>
      )}
      <div ref={logsContainerRef} onScroll={onScroll} className="logs-scroll">
        {activeTab === 'logs' && (
          <>
            {filteredLogs.length === 0 && (
              <div className="empty-state">
                No logs for {logScope === 'all' ? 'any account' : (activeAccount || 'this account')} yet.
              </div>
            )}
            {groupByCycle && logGroups ? (
              logGroups.map(g => (
                <details key={g.id} className="log-cycle-group" open={g.id === 0}>
                  <summary className="log-cycle-summary">
                    {g.label}
                    <span className="log-cycle-count">{g.entries.length}</span>
                  </summary>
                  <div className="log-cycle-body">
                    {g.entries.map((entry, i) => (
                      <LogLine key={`${g.id}-${i}-${entry.msg?.slice(0, 24)}`} entry={entry} />
                    ))}
                  </div>
                </details>
              ))
            ) : (
              filteredLogs.map((entry, i) => (
                <LogLine key={`${i}-${entry.msg?.slice(0, 32)}`} entry={entry} />
              ))
            )}
          </>
        )}
        {activeTab === 'success' && (
          <>
            {displaySuccessList.length === 0 && (
              <div className="empty-state">No successful forwards yet.</div>
            )}
            {successNewestFirst.map((group, i) => (
              <div key={`${i}-${group}`} className="log-result-line log-result-line--ok">
                <span>✓</span>
                <a href={`https://t.me/${group}`} target="_blank" rel="noreferrer">{group}</a>
              </div>
            ))}
          </>
        )}
        {activeTab === 'failed' && (
          <>
            {displayFailedList.length === 0 && (
              <div className="empty-state">No failures yet.</div>
            )}
            {failedNewestFirst.map((item, i) => (
              <div key={`${i}-${item.group}`} className="log-result-line log-result-line--fail">
                <span className="log-result-group">✗ {item.group}</span>
                <span className="log-result-reason">{item.reason}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}

export function LogToolbarActions({
  activeTab,
  displayLogs,
  displayLogsNewestFirst,
  displaySuccessNewestFirst,
  displayFailedNewestFirst,
  clearingLogs,
  copied,
  clearDisabled = false,
  clearTitle = 'Clear logs for selected account',
  onClear,
  onCopy,
}) {
  return (
    <div className="logs-toolbar-actions">
      {activeTab === 'logs' && (
        <Button
          variant="danger"
          size="xs"
          className="logs-toolbar-btn logs-toolbar-btn--danger btn-with-loader"
          onClick={onClear}
          disabled={displayLogs.length === 0 || clearingLogs || clearDisabled}
          loading={clearingLogs}
          loadingLabel="Clearing…"
          title={clearTitle}
        >
          Clear
        </Button>
      )}
      <Button
        variant="toolbar"
        size="xs"
        className={`logs-toolbar-btn logs-toolbar-btn--copy${copied ? ' logs-toolbar-btn--copied' : ''}`}
        onClick={onCopy}
        disabled={displayLogs.length === 0 && activeTab === 'logs'}
        title="Copy list to clipboard"
      >
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  )
}
