import React from 'react'

/** Decorative mini chart for stat cards (Sigma-style). */
export function MobSparkline({ color = '#22c55e', variant = 'line' }) {
  const stroke = color
  const fill = `${color}33`
  if (variant === 'bars') {
    return (
      <svg className="mob-sparkline" viewBox="0 0 48 20" aria-hidden>
        <rect x="4" y="12" width="6" height="8" fill={fill} rx="1" />
        <rect x="14" y="8" width="6" height="12" fill={fill} rx="1" />
        <rect x="24" y="4" width="6" height="16" fill={fill} rx="1" />
        <rect x="34" y="10" width="6" height="10" fill={fill} rx="1" />
      </svg>
    )
  }
  if (variant === 'flat') {
    return (
      <svg className="mob-sparkline" viewBox="0 0 48 20" aria-hidden>
        <line x1="4" y1="14" x2="44" y2="14" stroke={stroke} strokeWidth="2" strokeOpacity="0.5" />
      </svg>
    )
  }
  return (
    <svg className="mob-sparkline" viewBox="0 0 48 20" aria-hidden>
      <polyline
        points="4,16 12,10 20,12 28,6 36,8 44,4"
        fill="none"
        stroke={stroke}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
