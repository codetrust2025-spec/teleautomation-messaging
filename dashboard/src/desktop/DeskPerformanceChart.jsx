import React from 'react'

/** Decorative performance area chart (Sigma-style). */
export function DeskPerformanceChart({ postsSent = 0, tickSent = 0, successRate = 0 }) {
  const h1 = Math.min(90, 20 + postsSent * 0.3)
  const h2 = Math.min(85, 15 + tickSent * 2)
  const h3 = Math.min(80, successRate * 0.7)
  return (
    <div className="desk-perf-chart">
      <div className="desk-perf-chart__legend">
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--green" />Posts sent</span>
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--blue" />Running now</span>
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--amber" />Current sent</span>
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--red" />Failed</span>
        <span><i className="desk-perf-chart__dot desk-perf-chart__dot--purple" />Success rate</span>
      </div>
      <svg className="desk-perf-chart__svg" viewBox="0 0 400 120" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id="deskAreaGreen" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="deskAreaBlue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          d={`M0,${120 - h1} Q100,${120 - h1 - 15} 200,${120 - h2} T400,${120 - h3} L400,120 L0,120 Z`}
          fill="url(#deskAreaGreen)"
        />
        <path
          d={`M0,${120 - h2 + 10} Q120,${120 - h3} 240,${120 - h1 + 20} T400,${120 - h2} L400,120 L0,120 Z`}
          fill="url(#deskAreaBlue)"
          opacity="0.7"
        />
        <polyline
          points={`0,${120 - h1} 80,${120 - h1 - 8} 160,${120 - h2} 240,${120 - h3 + 5} 320,${120 - h2 - 10} 400,${120 - h3}`}
          fill="none"
          stroke="#4ade80"
          strokeWidth="2"
        />
        <polyline
          points={`0,${120 - h2 + 15} 100,${120 - h3} 200,${120 - h1 + 5} 300,${120 - h2} 400,${120 - h3 + 12}`}
          fill="none"
          stroke="#60a5fa"
          strokeWidth="1.5"
          opacity="0.8"
        />
      </svg>
    </div>
  )
}
