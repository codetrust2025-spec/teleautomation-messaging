import React, { useMemo } from 'react'
import { rankAccountsByPerformance } from '../utils/accountPerformance.js'
import { SubscriptionBadge } from './SubscriptionBadge.jsx'

/**
 * Horizontal bar chart — accounts sorted by messages sent in last 24h (high → low).
 */
export function AccountPerformanceChart({ perAccount, accountInfo, statsWindow, subscriptionSlots = [], rankingOnly = false }) {
  const subs = Array.isArray(subscriptionSlots) ? subscriptionSlots : []
  const windowNote = statsWindow === 'since_reset'
    ? 'since last reset'
    : 'in the rolling last 24h'
  const ranked = useMemo(
    () => rankAccountsByPerformance(perAccount, accountInfo),
    [perAccount, accountInfo],
  )

  const maxSent24h = useMemo(
    () => Math.max(1, ...ranked.map((r) => r.sent24h)),
    [ranked],
  )

  if (ranked.length === 0) return null

  return (
    <section className="perf-chart" aria-label="Account performance ranking last 24 hours">
      <header className="perf-chart-header">
        <h4 className="perf-chart-title">Top performers</h4>
        <p className="perf-chart-sub">
          {rankingOnly
            ? 'Relative ranking by forwards — bar length only'
            : <>Sorted high → low by <strong>forwarded</strong> {windowNote}</>}
        </p>
      </header>

      <ol className="perf-chart-list">
        {ranked.map((row, index) => {
          const pct = Math.round((row.sent24h / maxSent24h) * 100)
          const rank = index + 1
          const rankClass =
            rank === 1 ? 'perf-chart-rank--1' : rank === 2 ? 'perf-chart-rank--2' : rank === 3 ? 'perf-chart-rank--3' : ''

          return (
            <li key={row.slot} className={`perf-chart-row${subs.includes(row.slot) ? ' perf-chart-row--subscription' : ''}`}>
              <span className={`perf-chart-rank ${rankClass}`} aria-hidden>
                {rank}
              </span>
              <div className="perf-chart-body">
                <div className="perf-chart-label-row">
                  <span className="perf-chart-slot" title={row.displayName}>
                    {subs.includes(row.slot) && (
                      <span className="perf-chart-sub-mark" title="Subscription account">◆</span>
                    )}
                    {row.shortLabel}
                    {subs.includes(row.slot) && <SubscriptionBadge variant="icon" />}
                  </span>
                  <span className="perf-chart-name" title={row.displayName}>
                    {row.displayName}
                  </span>
                  {!rankingOnly && (
                  <span className="perf-chart-value" title="Successful sends in last 24 hours">
                    {row.sent24h}
                  </span>
                  )}
                </div>
                <div
                  className="perf-chart-track"
                  role="img"
                  aria-label={`${row.displayName}: rank ${rank}`}
                >
                  <div
                    className="perf-chart-bar perf-chart-bar--24h"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                {!rankingOnly && (
                <div className="perf-chart-meta">
                  {row.sent24h > 0 ? (
                    <span className="perf-chart-meta--24h">{row.sent24h} forwarded</span>
                  ) : (
                    <span className="perf-chart-meta--idle">No forwards in window</span>
                  )}
                  {row.running && (
                    <span className="perf-chart-meta--live">Running now</span>
                  )}
                </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
