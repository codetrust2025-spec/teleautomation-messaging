import React from 'react'
import { SegmentedControl } from './SegmentedControl.jsx'
import { OptionPickList } from './OptionPickList.jsx'
import { useCompactLayout } from '../../utils/useCompactLayout.js'

/**
 * Wide screen: segmented buttons. Narrow: tap tiles (no scroll, no native select sheet).
 */
export function ResponsiveOptions({
  options,
  value,
  onChange,
  label,
  className = '',
  segmentedClassName = '',
  role = 'group',
  compactColumns,
}) {
  const compact = useCompactLayout()
  const columns = compactColumns ?? (options.length <= 2 ? 2 : options.length <= 3 ? 3 : 2)

  if (compact) {
    return (
      <OptionPickList
        className={['responsive-options', 'responsive-options--compact', className].filter(Boolean).join(' ')}
        label={label}
        options={options}
        value={value}
        onChange={onChange}
        columns={columns}
        role={role}
      />
    )
  }

  return (
    <div className={['responsive-options', className].filter(Boolean).join(' ')}>
      <SegmentedControl
        className={['responsive-options__segments', segmentedClassName].filter(Boolean).join(' ')}
        label={label}
        options={options}
        value={value}
        onChange={onChange}
        role={role}
      />
    </div>
  )
}
