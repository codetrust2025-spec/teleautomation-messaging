import React from 'react'

export function MobHealthRing({ percent = 100, label = 'Healthy' }) {
  const p = Math.min(100, Math.max(0, percent))
  const deg = (p / 100) * 360
  return (
    <div className="mob-health-ring" style={{ '--ring-deg': `${deg}deg` }} aria-hidden>
      <div className="mob-health-ring__inner">
        <span className="mob-health-ring__pct">{Math.round(p)}%</span>
        <span className="mob-health-ring__label">{label}</span>
      </div>
    </div>
  )
}
