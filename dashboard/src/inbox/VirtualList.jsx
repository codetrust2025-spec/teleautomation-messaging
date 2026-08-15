import React, { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Fixed-height windowed list for large collections (conversations, flat timelines).
 */
export function VirtualList({
  items,
  itemHeight,
  renderItem,
  className = '',
  overscan = 4,
  getKey,
}) {
  const containerRef = useRef(null)
  const [viewportH, setViewportH] = useState(320)
  const [scrollTop, setScrollTop] = useState(0)

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => {
      setViewportH(el.clientHeight || 320)
    })
    ro.observe(el)
    setViewportH(el.clientHeight || 320)
    return () => ro.disconnect()
  }, [])

  const onScroll = useCallback(e => {
    setScrollTop(e.currentTarget.scrollTop)
  }, [])

  const totalH = items.length * itemHeight
  const start = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan)
  const visibleCount = Math.ceil(viewportH / itemHeight) + overscan * 2
  const end = Math.min(items.length, start + visibleCount)
  const offsetY = start * itemHeight

  return (
    <div
      ref={containerRef}
      className={className}
      onScroll={onScroll}
      role="list"
    >
      <div className="tg-virtual-spacer" style={{ height: totalH }}>
        {/* padding-top avoids transform — iOS Safari often drops taps on transformed ancestors */}
        <div className="tg-virtual-window" style={{ paddingTop: offsetY }}>
          {items.slice(start, end).map((item, i) => {
            const index = start + i
            const key = getKey ? getKey(item, index) : index
            return (
              <div
                key={key}
                className="tg-virtual-row"
                style={{ height: itemHeight }}
                role="listitem"
              >
                {renderItem(item, index)}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
