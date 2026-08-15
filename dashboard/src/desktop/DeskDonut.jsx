import React from 'react'

export function DeskDonut({ value, max = 100, color = '#22c55e', label, sublabel }) {
  const pct = max > 0 ? Math.min(1, value / max) : 0
  const deg = pct * 360
  return (
    <div className="desk-donut" style={{ '--donut-color': color, '--donut-deg': `${deg}deg` }}>
      <div className="desk-donut__ring" aria-hidden>
        <div className="desk-donut__hole">
          <span className="desk-donut__value">
            {sublabel === '%'
              ? `${Math.round(value)}%`
              : sublabel === '—'
                ? '—'
                : value}
          </span>
        </div>
      </div>
      <span className="desk-donut__label">{label}</span>
      {sublabel && <span className="desk-donut__sub">{sublabel}</span>}
    </div>
  )
}
