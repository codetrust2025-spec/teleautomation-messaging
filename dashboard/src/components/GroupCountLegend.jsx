import React from 'react'

/**
 * Explains master catalog vs fleet send slices vs one account's slice.
 */
export function GroupCountLegend({
  master = 0,
  fleetSlice = 0,
  accountSlice = null,
  accountLabel = null,
  className = '',
}) {
  const parts = [
    {
      key: 'master',
      label: 'Master',
      value: master,
      title: 'Total group names in groups_list.json (shared catalog for all accounts)',
    },
    {
      key: 'fleet',
      label: 'Fleet slices',
      value: fleetSlice,
      title:
        'Sum of each logged-in account\'s send list this cycle (master split across accounts, minus dead names)',
    },
  ]

  if (accountSlice != null && accountSlice >= 0) {
    parts.push({
      key: 'account',
      label: accountLabel ? `${accountLabel} slice` : 'This account',
      value: accountSlice,
      title: 'Groups assigned to the selected account for posting (not the full master list)',
    })
  }

  return (
    <p
      className={`group-count-legend${className ? ` ${className}` : ''}`}
      role="note"
      aria-label="Group count legend"
    >
      {parts.map((p, i) => (
        <React.Fragment key={p.key}>
          {i > 0 && <span className="group-count-legend-sep" aria-hidden> · </span>}
          <span className="group-count-legend-item" title={p.title}>
            <span className="group-count-legend-label">{p.label}:</span>{' '}
            <strong>{p.value}</strong>
          </span>
        </React.Fragment>
      ))}
    </p>
  )
}
