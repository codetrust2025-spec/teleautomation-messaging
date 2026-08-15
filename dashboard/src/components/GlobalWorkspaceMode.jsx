import React from 'react'
import { SegmentedControl } from './ui/SegmentedControl.jsx'
import { WORKSPACE_MODE_OPTIONS } from '../utils/workspaceMode.js'

/**
 * Top-level Forward vs Campaign — filters the whole dashboard to one feature set.
 */
export function GlobalWorkspaceMode({ value, onChange, className = '' }) {
  return (
    <div className={`global-workspace-mode${className ? ` ${className}` : ''}`}>
      <SegmentedControl
        className="global-workspace-mode__control"
        label="Workspace"
        options={WORKSPACE_MODE_OPTIONS}
        value={value}
        onChange={onChange}
        role="tablist"
      />
      <p className="global-workspace-mode__hint">
        {value === 'forwarding'
          ? 'Forwarding only — accounts, setup, and stats for 24/7 or manual forward.'
          : 'Campaign only — accounts, group lists, cycles, and campaign stats.'}
      </p>
    </div>
  )
}
