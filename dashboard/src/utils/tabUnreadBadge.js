/**
 * Browser tab unread indicator — WhatsApp-style "(N) Title" + favicon badge.
 */

import { formatUnreadBadgeCount } from './inboxUnread.js'

const BADGE_FILL = '#25d366'
const BADGE_TEXT = '#ffffff'

let baseTitle = ''
let baseFaviconUrl = ''
let faviconLink = null
let faviconImage = null
let faviconReady = false

function readBaseTitle() {
  if (baseTitle) return baseTitle
  const raw = (document.title || 'TeleAutomation').trim()
  baseTitle = raw.replace(/^\(\d+\+?\)\s+/, '')
  return baseTitle
}

function defaultFaviconSvg() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="8" fill="#5b21b6"/>
<path fill="#c4b5fd" d="M18 4 10 18h6l-4 10 12-16h-6z"/>
</svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

function ensureFaviconLink() {
  if (faviconLink) return faviconLink
  faviconLink =
    document.querySelector('link[rel="icon"]') ||
    document.querySelector('link[rel="shortcut icon"]')
  if (!faviconLink) {
    faviconLink = document.createElement('link')
    faviconLink.rel = 'icon'
    faviconLink.id = 'ta-app-icon'
    document.head.appendChild(faviconLink)
  }
  if (!faviconLink.href) {
    faviconLink.href = defaultFaviconSvg()
  }
  return faviconLink
}

function loadBaseFavicon() {
  if (faviconReady) return
  const link = ensureFaviconLink()
  baseFaviconUrl = link.href || defaultFaviconSvg()
  if (!faviconImage) {
    faviconImage = new Image()
    faviconImage.crossOrigin = 'anonymous'
    faviconImage.onload = () => {
      faviconReady = true
      syncTabUnreadBadge(lastUnreadCount)
    }
    faviconImage.onerror = () => {
      baseFaviconUrl = defaultFaviconSvg()
      faviconImage.src = baseFaviconUrl
    }
  }
  faviconImage.src = baseFaviconUrl
}

let lastUnreadCount = 0

function drawFaviconBadge(count) {
  const link = ensureFaviconLink()
  const n = Math.max(0, Number(count) || 0)
  if (n <= 0) {
    link.href = baseFaviconUrl || defaultFaviconSvg()
    return
  }
  if (!faviconReady || !faviconImage?.naturalWidth) {
    link.href = baseFaviconUrl || defaultFaviconSvg()
    return
  }

  const size = 32
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.drawImage(faviconImage, 0, 0, size, size)

  const label = formatUnreadBadgeCount(n) || String(n)
  const r = n > 9 ? 11 : 10
  const cx = size - r + 1
  const cy = r - 1

  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fillStyle = BADGE_FILL
  ctx.fill()
  ctx.strokeStyle = '#0f1117'
  ctx.lineWidth = 1.5
  ctx.stroke()

  ctx.fillStyle = BADGE_TEXT
  ctx.font = `bold ${label.length > 2 ? 8 : 11}px system-ui, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, cx, cy + 0.5)

  link.href = canvas.toDataURL('image/png')
}

/**
 * Update document title and favicon for unread inbox DMs.
 * @param {number} unreadCount
 */
export function syncTabUnreadBadge(unreadCount) {
  lastUnreadCount = Math.max(0, Number(unreadCount) || 0)
  readBaseTitle()
  loadBaseFavicon()

  if (lastUnreadCount > 0) {
    const badge = formatUnreadBadgeCount(lastUnreadCount)
    document.title = `(${badge}) ${baseTitle}`
  } else {
    document.title = baseTitle
  }

  drawFaviconBadge(lastUnreadCount)
}

export function resetTabUnreadBadge() {
  lastUnreadCount = 0
  readBaseTitle()
  document.title = baseTitle
  const link = ensureFaviconLink()
  link.href = baseFaviconUrl || defaultFaviconSvg()
}
