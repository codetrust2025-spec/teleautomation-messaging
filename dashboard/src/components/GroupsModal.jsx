import React, { useMemo, useState } from 'react'
import { OverlayLoader } from '../Loader.jsx'
import { Button } from './ui/Button.jsx'
import { ModalShell } from './ui/ModalShell.jsx'
import { SegmentedControl } from './ui/SegmentedControl.jsx'

export function GroupsModal({
  open,
  onClose,
  groups,
  loading,
  onDownload,
  slotLists,
}) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')

  const activeSet = useMemo(() => new Set(slotLists?.active || []), [slotLists])
  const deadSet = useMemo(() => new Set(slotLists?.dead || []), [slotLists])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return groups.filter(g => {
      if (q && !g.toLowerCase().includes(q)) return false
      if (filter === 'active') return activeSet.has(g)
      if (filter === 'dead') return deadSet.has(g)
      return true
    })
  }, [groups, search, filter, activeSet, deadSet])

  if (!open) return null

  const summary = slotLists
    ? `${groups.length} master · ${slotLists.active_count ?? activeSet.size} active · ${slotLists.dead_count ?? deadSet.size} dead`
    : `${groups.length} groups`

  return (
    <ModalShell
      open={open}
      onClose={onClose}
      title="Groups list"
      subtitle={summary}
      labelledBy="groups-modal-title"
      actions={(
        <div className="btn-row">
          <Button variant="success" size="sm" onClick={onDownload}>Download</Button>
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      )}
    >
        {loading && <OverlayLoader label="Loading groups list…" />}

        {slotLists && (
          <SegmentedControl
            className="modal-filters"
            label="Filter groups"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: `All (${groups.length})` },
              { value: 'active', label: `Active (${activeSet.size})` },
              { value: 'dead', label: `Dead (${deadSet.size})` },
            ]}
          />
        )}

        <input
          className="input input--search modal-search"
          placeholder="Search groups…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />

        <div className="modal-list">
          {filtered.map((g, i) => {
            const isDead = deadSet.has(g)
            const isActive = activeSet.has(g)
            return (
              <div key={`${g}-${i}`} className="modal-list-row">
                <span className="modal-list-index">{i + 1}</span>
                <a href={`https://t.me/${g}`} target="_blank" rel="noreferrer" className="modal-list-link">{g}</a>
                {slotLists && (
                  <span className={`modal-list-tag${isDead ? ' modal-list-tag--dead' : isActive ? ' modal-list-tag--active' : ''}`}>
                    {isDead ? 'dead' : isActive ? 'active' : '—'}
                  </span>
                )}
              </div>
            )
          })}
          {filtered.length === 0 && (
            <p className="empty-state">No groups match your search.</p>
          )}
        </div>
    </ModalShell>
  )
}
