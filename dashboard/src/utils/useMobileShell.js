import { useEffect, useState } from 'react'

/** Phone-only — swap to MobileApp shell (bottom nav). Tablets keep desktop sidebar. */
export const MOBILE_SHELL_MQ = '(max-width: 767px)'

export function useMobileShell() {
  const [mobile, setMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(MOBILE_SHELL_MQ).matches
  })

  useEffect(() => {
    const mq = window.matchMedia(MOBILE_SHELL_MQ)
    const sync = () => setMobile(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  return mobile
}
