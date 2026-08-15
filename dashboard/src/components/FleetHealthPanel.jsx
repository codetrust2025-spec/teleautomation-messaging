import React, { useMemo } from 'react'
import {
  buildFleetHealthRows,
  formatPostsPerHour,
  sortFleetHealthRows,
} from '../utils/fleetHealth.js'
import { SABHI_HEALTH } from '../utils/sabAccountsUi.js'
import { SubscriptionBadge } from './SubscriptionBadge.jsx'

function healthBarClass(health) {
  const h = health ?? 100
  if (h < 50) return 'fleet-health-bar--critical'
  if (h < 80) return 'fleet-health-bar--warn'
  return 'fleet-health-bar--ok'
}

function statusLabel(status, running) {
  if (status === 'flood_wait') return 'Flood wait'
  if (status === 'rate_limited') return 'Rate limited'
  if (status === 'sleeping') return 'Sleeping'
  if (status === 'running' || running) return 'Running'
  if (status === 'active') return 'Active'
  if (status === 'waiting') return 'Waiting'
  if (status === 'stopped') return 'Stopped'
  return status || '—'
}

export function FleetHealthPanel({ perAccount, accountInfo, statsWindow, dailyStats, subscriptionSlots = [] }) {
  const subs = Array.isArray(subscriptionSlots) ? subscriptionSlots : []
  const resetTimestamp = dailyStats?.reset_timestamp ?? 0
  const windowNote =
    statsWindow === 'since_reset' ? 'since last reset' : 'rolling 24h'

  const { rows, topRate, needsCount } = useMemo(() => {
    const built = sortFleetHealthRows(
      buildFleetHealthRows(perAccount, accountInfo, statsWindow, resetTimestamp),
    )
    const rates = built.map((r) => r.postsPerHour).filter((n) => n > 0)
    const top = rates.length ? Math.max(...rates) : 0
    const needs = built.filter((r) => r.attention).length
    return { rows: built, topRate: top, needsCount: needs }
  }, [perAccount, accountInfo, statsWindow, resetTimestamp])

  if (rows.length === 0) return null

  return (
    <section className="fleet-health" aria-label={`${SABHI_HEALTH} overview`}>
      <header className="fleet-health-header">
        <div>
          <h4 className="fleet-health-title">{SABHI_HEALTH}</h4>
          <p className="fleet-health-sub">
            Health, forwards, and posts/hour ({windowNote}) — fix flagged accounts first
          </p>
        </div>
        {needsCount > 0 ? (
          <span className="fleet-health-alert-pill" role="status">
            {needsCount} need{needsCount === 1 ? 's' : ''} attention
          </span>
        ) : (
          <span className="fleet-health-ok-pill" role="status">All clear</span>
        )}
      </header>

      {topRate > 0 && (
        <p className="fleet-health-benchmark" role="note">
          Top rate: <strong>{formatPostsPerHour(topRate)}/hr</strong>
          {' '}— bring others closer by keeping workers running and health above 80%
        </p>
      )}

      <div className="fleet-health-table-wrap">
        <table className="fleet-health-table">
          <thead>
            <tr>
              <th scope="col">Account</th>
              <th scope="col">Health</th>
              <th scope="col">Forwards</th>
              <th scope="col">Posts/hr</th>
              <th scope="col">Status</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const health = row.health ?? (row.loggedIn ? 100 : 0)
              const ratePct = topRate > 0
                ? Math.min(100, Math.round((row.postsPerHour / topRate) * 100))
                : 0
              return (
                <tr
                  key={row.slot}
                  className={
                    `${row.attention ? `fleet-health-row fleet-health-row--${row.attention}` : 'fleet-health-row'}${subs.includes(row.slot) ? ' fleet-health-row--subscription' : ''}`
                  }
                >
                  <td className="fleet-health-cell fleet-health-cell--name">
                    <span className="fleet-health-slot">
                      {subs.includes(row.slot) && (
                        <span className="fleet-health-sub-mark" title="Subscription account">◆</span>
                      )}
                      {row.shortLabel}
                    </span>
                    <span className="fleet-health-name" title={row.displayName}>
                      {row.displayName}
                    </span>
                    {subs.includes(row.slot) && (
                      <SubscriptionBadge variant="dot" showLabel={false} title="Subscription account" />
                    )}
                  </td>
                  <td className="fleet-health-cell">
                    <div className="fleet-health-health">
                      <div
                        className="fleet-health-bar-track"
                        role="img"
                        aria-label={`Health ${Math.round(health)} percent`}
                      >
                        <div
                          className={`fleet-health-bar-fill ${healthBarClass(health)}`}
                          style={{ width: `${Math.max(0, Math.min(100, health))}%` }}
                        />
                      </div>
                      <span className="fleet-health-health-val">{Math.round(health)}%</span>
                    </div>
                  </td>
                  <td className="fleet-health-cell fleet-health-cell--num">
                    {row.forwards}
                  </td>
                  <td className="fleet-health-cell fleet-health-cell--num">
                    <span className="fleet-health-rate">{formatPostsPerHour(row.postsPerHour)}</span>
                    {topRate > 0 && row.postsPerHour > 0 && (
                      <span
                        className="fleet-health-rate-bar"
                        style={{ width: `${Math.max(8, ratePct)}%` }}
                        title={`${ratePct}% of top rate across accounts`}
                      />
                    )}
                  </td>
                  <td className="fleet-health-cell">
                    <span className={`fleet-health-status fleet-health-status--${row.status || 'idle'}`}>
                      {!row.loggedIn ? 'Not logged in' : statusLabel(row.status, row.running)}
                    </span>
                  </td>
                  <td className="fleet-health-cell fleet-health-cell--action">
                    {row.attentionHint ? (
                      <span className="fleet-health-hint">{row.attentionHint}</span>
                    ) : (
                      <span className="fleet-health-hint fleet-health-hint--ok">On track</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
