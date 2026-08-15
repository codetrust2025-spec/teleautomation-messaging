import React from 'react'

export function DashboardColumn({ id, title, subtitle, children, flush, headerActions, toolbar }) {
  return (
    <section className={`dashboard-column dashboard-column--${id}`} aria-label={title}>
      <header className="dashboard-column-header">
        <div className="dashboard-column-header-row">
          <div className="dashboard-column-header-text">
            <div className="dashboard-column-header-title">{title}</div>
            {subtitle ? <div className="dashboard-column-header-sub">{subtitle}</div> : null}
          </div>
          {headerActions ? (
            <div className={`dashboard-column-header-actions${id === 'right' ? ' logs-header-actions' : ''}`}>
              {headerActions}
            </div>
          ) : null}
        </div>
      </header>
      {toolbar ? <div className="dashboard-column-toolbar">{toolbar}</div> : null}
      <div className={`dashboard-column-body${flush ? ' dashboard-column-body--flush' : ''}`}>
        {children}
      </div>
    </section>
  )
}
