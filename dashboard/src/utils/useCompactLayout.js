import { useEffect, useState } from 'react'

/** Phone / narrow tablet — use dropdowns instead of sideways tab scroll. */
export const COMPACT_LAYOUT_MQ = '(max-width: 1023px)'

export function useCompactLayout() {
  const [compact, setCompact] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(COMPACT_LAYOUT_MQ).matches
  })

  useEffect(() => {
    const mq = window.matchMedia(COMPACT_LAYOUT_MQ)
    const sync = () => setCompact(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  return compact
}
