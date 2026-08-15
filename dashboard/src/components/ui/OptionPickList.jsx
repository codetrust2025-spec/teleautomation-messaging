import React from 'react'

/**
 * Mobile-friendly choices: tap tiles in a grid (no sideways scroll, no native picker sheet).
 */
export function OptionPickList({
  options,
  value,
  onChange,
  label,
  className = '',
  columns = 2,
  role = 'group',
}) {
  const colClass = columns === 1 ? 'option-pick-list--cols-1' : columns >= 3 ? 'option-pick-list--cols-3' : 'option-pick-list--cols-2'

  return (
    <div
      className={['option-pick-list', colClass, className].filter(Boolean).join(' ')}
      role={role}
      aria-label={label}
    >
      {options.map(option => {
        const active = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            className={[
              'option-pick-list__btn',
              active ? 'option-pick-list__btn--active' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            onClick={() => onChange(option.value)}
            disabled={option.disabled}
            role={option.role === 'tab' ? 'tab' : undefined}
            aria-selected={option.role === 'tab' ? active : undefined}
            aria-pressed={option.role !== 'tab' ? active : undefined}
          >
            <span className="option-pick-list__label">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
