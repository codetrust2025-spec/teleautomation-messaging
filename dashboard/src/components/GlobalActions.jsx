import React from 'react'
import { Spinner } from '../Loader.jsx'
import { useConfirm } from '../context/ConfirmContext.jsx'
import { Button } from './ui/Button.jsx'

export function GlobalActions({
  connected,
  canStartMore,
  anyRunning,
  bulkActionLoading,
  hardRefreshing,
  totalListLoading,
  onStartAll,
  onStopAll,
  onHardRefresh,
  onTotalList,
}) {
  const { confirm } = useConfirm()

  async function handleStopAll() {
    const ok = await confirm({
      title: 'Stop all accounts?',
      message: 'All running workers will stop. You can start them again when ready.',
      confirmLabel: 'Stop all',
      cancelLabel: 'Keep running',
      variant: 'danger',
    })
    if (ok) onStopAll()
  }

  return (
    <div className="app-header-actions">
      <div className="app-header-actions__primary">
        {anyRunning ? (
          <Button
            variant="danger"
            size="sm"
            className="app-header-btn app-header-btn--primary-action"
            onClick={handleStopAll}
            disabled={bulkActionLoading}
            loading={bulkActionLoading === 'stop'}
            loadingLabel="…"
            title="Stop all running accounts"
            aria-label="Stop all"
          >
            <span className="app-header-btn-icon" aria-hidden>⏹</span>
            <span className="app-header-btn-label">Stop all</span>
          </Button>
        ) : (
          <Button
            variant="success"
            size="sm"
            className="app-header-btn app-header-btn--primary-action"
            onClick={onStartAll}
            disabled={!canStartMore || bulkActionLoading}
            loading={bulkActionLoading === 'start'}
            loadingLabel="…"
            title={
              canStartMore
                ? 'Start all logged-in idle accounts (24/7)'
                : 'No logged-in accounts ready to start'
            }
            aria-label="Start all"
          >
            <span className="app-header-btn-icon" aria-hidden>▶</span>
            <span className="app-header-btn-label">Start all</span>
          </Button>
        )}

        <div
          className="connection-pill app-header-control connection-pill--compact"
          title={connected ? 'Live updates from backend' : 'Cannot reach backend — retrying every 3s'}
        >
          <span className={`connection-dot${connected ? ' connection-dot--on' : ''}`} />
          {!connected && <Spinner size={12} />}
          <span className="connection-label">
            {connected ? 'Live' : '…'}
          </span>
        </div>
      </div>

      <div className="app-header-actions__secondary app-header-actions__secondary--inline">
        {onTotalList && (
          <Button
            variant="ghost"
            size="sm"
            className="app-header-btn app-header-btn--icon"
            onClick={onTotalList}
            disabled={totalListLoading}
            loading={totalListLoading}
            loadingLabel="…"
            title="Download joined groups CSV for all accounts"
            aria-label="Total list CSV"
          >
            <span className="app-header-btn-icon" aria-hidden>📋</span>
            <span className="app-header-btn-label">List</span>
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="app-header-btn app-header-btn--icon"
          onClick={onHardRefresh}
          disabled={hardRefreshing}
          loading={hardRefreshing}
          loadingLabel="…"
          title="Reload page and fetch latest state"
          aria-label="Refresh"
        >
          <span className="app-header-btn-icon" aria-hidden>↻</span>
          <span className="app-header-btn-label">Refresh</span>
        </Button>
      </div>
    </div>
  )
}
