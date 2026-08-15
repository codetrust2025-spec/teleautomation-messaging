import React, { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'telegram-forward-column-sizes-v3'
const DEFAULT_SIZES = { left: 42, center: 23, right: 35 }
const MIN_PCT = 14
const RESIZE_MIN_WIDTH = 900

function loadSizes() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SIZES }
    const p = JSON.parse(raw)
    const left = Number(p.left)
    const center = Number(p.center)
    const right = Number(p.right)
    if (
      left >= MIN_PCT && center >= MIN_PCT && right >= MIN_PCT &&
      Math.abs(left + center + right - 100) < 0.5
    ) {
      return { left, center, right }
    }
  } catch {
    /* ignore */
  }
  return { ...DEFAULT_SIZES }
}

function saveSizes(sizes) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sizes))
  } catch {
    /* ignore */
  }
}

function clamp(n, lo, hi) {
  return Math.max(lo, Math.min(hi, n))
}

function ColumnResizeHandle({ onPointerDown, label }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      title="Drag to resize columns"
      className="column-resize-handle"
      onMouseDown={onPointerDown}
      onDoubleClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
      }}
    >
      <span className="column-resize-handle-grip" aria-hidden>⋮</span>
    </div>
  )
}

/**
 * Three-column layout with draggable dividers (desktop).
 * Below 900px width uses CSS stack layout — no drag handles.
 */
export function ResizableDashboardLayout({ left, center, right }) {
  const onlyLeft = !center && !right
  const twoCol = !right
  const [sizes, setSizes] = useState(loadSizes)
  const [canResize, setCanResize] = useState(
    () => typeof window !== 'undefined' && window.innerWidth >= RESIZE_MIN_WIDTH,
  )
  const containerRef = useRef(null)
  const dragRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)

  useEffect(() => {
    const onResize = () => setCanResize(window.innerWidth >= RESIZE_MIN_WIDTH)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const endDrag = useCallback(() => {
    dragRef.current = null
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  useEffect(() => {
    if (!isDragging) return undefined

    const onMove = (e) => {
      const d = dragRef.current
      if (!d || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const totalW = rect.width
      if (totalW < 1) return
      const deltaPct = ((e.clientX - d.startX) / totalW) * 100

      setSizes(() => {
        if (d.index === 0) {
          const newLeft = clamp(
            d.start.left + deltaPct,
            MIN_PCT,
            100 - MIN_PCT - MIN_PCT - d.start.right,
          )
          const shift = newLeft - d.start.left
          return {
            left: newLeft,
            center: d.start.center - shift,
            right: d.start.right,
          }
        }
        const newCenter = clamp(
          d.start.center + deltaPct,
          MIN_PCT,
          100 - MIN_PCT - d.start.left,
        )
        const shift = newCenter - d.start.center
        return {
          left: d.start.left,
          center: newCenter,
          right: d.start.right - shift,
        }
      })
    }

    const onUp = () => {
      setSizes((s) => {
        saveSizes(s)
        return s
      })
      setIsDragging(false)
      endDrag()
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
  }, [isDragging, endDrag])

  const startDrag = (index) => (e) => {
    if (!canResize) return
    e.preventDefault()
    dragRef.current = { index, startX: e.clientX, start: { ...sizes } }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    setIsDragging(true)
  }

  if (onlyLeft) {
    return (
      <div className="dashboard-resize-wrap dashboard-resize-wrap--single">
        <div className="dashboard-resize-row">
          <div className="dashboard-resize-pane" style={{ width: '100%' }}>
            {left}
          </div>
        </div>
      </div>
    )
  }

  if (!canResize) {
    return (
      <div
        className={`dashboard-grid dashboard-grid--auto${twoCol ? ' dashboard-grid--two-col' : ''}`}
      >
        {left}
        {center}
        {right}
      </div>
    )
  }

  if (twoCol) {
    const total = Math.max(1, sizes.left + sizes.center)
    const leftPct = (sizes.left / total) * 100
    return (
      <div className="dashboard-resize-wrap dashboard-resize-wrap--two-col">
        <div ref={containerRef} className="dashboard-resize-row">
          <div className="dashboard-resize-pane" style={{ width: `${leftPct}%` }}>
            {left}
          </div>
          <ColumnResizeHandle
            label="Resize setup and progress columns"
            onPointerDown={startDrag(0)}
          />
          <div className="dashboard-resize-pane" style={{ width: `${100 - leftPct}%` }}>
            {center}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="dashboard-resize-wrap">
      <div ref={containerRef} className="dashboard-resize-row">
        <div className="dashboard-resize-pane" style={{ width: `${sizes.left}%` }}>
          {left}
        </div>
        <ColumnResizeHandle
          label="Resize setup and progress columns"
          onPointerDown={startDrag(0)}
        />
        <div className="dashboard-resize-pane" style={{ width: `${sizes.center}%` }}>
          {center}
        </div>
        <ColumnResizeHandle
          label="Resize progress and logs columns"
          onPointerDown={startDrag(1)}
        />
        <div className="dashboard-resize-pane" style={{ width: `${sizes.right}%` }}>
          {right}
        </div>
      </div>
    </div>
  )
}
