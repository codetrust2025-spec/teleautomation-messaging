import React, { useEffect, useState } from 'react'
import {
  formatQuietHoursRange,
  isInQuietHours,
  isQuietHoursEnabled,
  msUntilQuietHoursEnd,
  setQuietHoursEnabled,
} from '../utils/soundQuietHours.js'

function formatResumeIn(ms) {
  const totalMin = Math.ceil(ms / 60000)
  if (totalMin < 60) return `~${totalMin}m`
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  return m > 0 ? `~${h}h ${m}m` : `~${h}h`
}

export function SoundQuietHoursToggle() {
  const [enabled, setEnabled] = useState(isQuietHoursEnabled)
  const [mutedNow, setMutedNow] = useState(isInQuietHours)
  const [resumeIn, setResumeIn] = useState('')

  useEffect(() => {
    const refresh = () => {
      setEnabled(isQuietHoursEnabled())
      const quiet = isInQuietHours()
      setMutedNow(quiet)
      setResumeIn(quiet ? formatResumeIn(msUntilQuietHoursEnd()) : '')
    }
    refresh()
    const onChange = () => refresh()
    window.addEventListener('sound-quiet-hours-change', onChange)
    const tick = window.setInterval(refresh, 60000)
    return () => {
      window.removeEventListener('sound-quiet-hours-change', onChange)
      clearInterval(tick)
    }
  }, [])

  function onToggle(e) {
    const on = e.target.checked
    setQuietHoursEnabled(on)
    setEnabled(on)
    setMutedNow(isInQuietHours())
  }

  const range = formatQuietHoursRange()

  return (
    <label
      className={`sound-quiet-hours${mutedNow ? ' sound-quiet-hours--active' : ''}`}
      title={`When on, no DM chime or unread alert music from ${range} (your local time)`}
    >
      <input
        type="checkbox"
        className="sound-quiet-hours-input"
        checked={enabled}
        onChange={onToggle}
      />
      <span className="sound-quiet-hours-text">
        <span className="sound-quiet-hours-label">Quiet hours</span>
        <span className="sound-quiet-hours-range">{range}</span>
        {enabled && mutedNow && (
          <span className="sound-quiet-hours-status">Sounds off · resumes {resumeIn}</span>
        )}
      </span>
    </label>
  )
}
