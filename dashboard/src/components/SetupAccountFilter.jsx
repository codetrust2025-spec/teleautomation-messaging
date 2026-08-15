import React from 'react'
import { ResponsiveOptions } from './ui/ResponsiveOptions.jsx'
import { WORKSPACE_CAMPAIGN, WORKSPACE_FORWARDING } from '../utils/workspaceMode.js'

const FILTER_OPTIONS = [
  { value: WORKSPACE_FORWARDING, label: 'Forward' },
  { value: WORKSPACE_CAMPAIGN, label: 'Campaign' },
]

/**
 * List filter only — which accounts appear in the picker (not how they run).
 */
export function SetupAccountFilter({ value, onChange, forwardCount = 0, campaignCount = 0 }) {
  const options = FILTER_OPTIONS.map(o => ({
    ...o,
    label: o.value === WORKSPACE_FORWARDING
      ? `Forward (${forwardCount})`
      : `Campaign (${campaignCount})`,
  }))

  return (
    <div className="setup-account-filter">
      <ResponsiveOptions
        className="setup-account-filter__control"
        segmentedClassName="setup-account-filter__segments"
        label="Show accounts"
        options={options}
        value={value}
        onChange={onChange}
        role="tablist"
        compactColumns={2}
      />
      <p className="setup-account-filter__hint">
        Filters the list. To switch one account, use <strong>Change method</strong> (step 2). <strong>Bulk</strong> for
        everyone.
      </p>
    </div>
  )
}
