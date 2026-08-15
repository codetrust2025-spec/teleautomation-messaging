/** Bumped on each production deploy so Vite emits a new app-[hash].js (cache bust). */
export const BUILD_STAMP = '2026-08-05T084000Z'

/** API base — Vite dev uses the dev-server proxy configured in vite.config.js. */
export const isDevFrontend = import.meta.env.DEV || window.location.port === '3000'
export const API = isDevFrontend
  ? ''
  : `${window.location.protocol}//${window.location.host}`
export const WS = isDevFrontend
  ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

const configuredOperationsUrl = String(import.meta.env.VITE_OPERATIONS_PUBLIC_URL || '').trim()
export const OPERATIONS_PUBLIC_URL = configuredOperationsUrl
  ? configuredOperationsUrl.replace(/\/$/, '')
  : (isDevFrontend ? `${window.location.protocol}//${window.location.hostname}:8001` : '')

export function operationsUrl(path = '') {
  if (!OPERATIONS_PUBLIC_URL) return ''
  const suffix = path ? (path.startsWith('/') ? path : `/${path}`) : ''
  return `${OPERATIONS_PUBLIC_URL}${suffix}`
}

export const COUNTRY_CODES = ['+91', '+1', '+44', '+971', '+61', '+65', '+60']
// Placeholder quick-pick numbers only — real account numbers must come from
// backend/account config, never be hardcoded here.
export const SAVED_PHONES = []
