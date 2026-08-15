import { API } from '../config.js'

export const WEB_PUSH_STORAGE_KEY = 'tf_web_push_enabled'

export function isWebPushSupported() {
  return typeof window !== 'undefined'
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && typeof Notification !== 'undefined'
}

export function isWebPushEnabled() {
  try {
    return localStorage.getItem(WEB_PUSH_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function setWebPushEnabled(enabled) {
  try {
    localStorage.setItem(WEB_PUSH_STORAGE_KEY, enabled ? '1' : '0')
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent('web-push-toggle'))
}

export function notificationPermission() {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.permission
}

export function isStandalonePwa() {
  try {
    return window.matchMedia('(display-mode: standalone)').matches
      || window.navigator.standalone === true
  } catch {
    return false
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i)
  return out
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return null
  try {
    const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
    await navigator.serviceWorker.ready
    return reg
  } catch (e) {
    console.warn('service worker registration failed', e)
    return null
  }
}

async function fetchVapidPublicKey() {
  const res = await fetch(`${API}/push/vapid-public-key`, { credentials: 'include' })
  if (!res.ok) throw new Error('Could not load push configuration')
  const data = await res.json()
  if (data.status !== 'ok' || !data.public_key) {
    throw new Error(data.message || 'Web Push not configured on server')
  }
  return data.public_key
}

async function getExistingSubscription(reg) {
  try {
    return await reg.pushManager.getSubscription()
  } catch {
    return null
  }
}

async function postSubscription(subscription, method = 'POST') {
  const res = await fetch(`${API}/push/subscribe`, {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ subscription: subscription.toJSON() }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || data.status === 'error') {
    throw new Error(data.message || data.detail || 'Push registration failed')
  }
  return data
}

export async function enableWebPush() {
  if (!isWebPushSupported()) {
    throw new Error('Push notifications are not supported in this browser')
  }
  if ((await Notification.requestPermission()) !== 'granted') {
    throw new Error('Notification permission denied')
  }
  const reg = await registerServiceWorker()
  if (!reg) throw new Error('Could not register service worker')
  const publicKey = await fetchVapidPublicKey()
  let sub = await getExistingSubscription(reg)
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    })
  }
  await postSubscription(sub, 'POST')
  setWebPushEnabled(true)
  return sub
}

export async function disableWebPush() {
  if (!('serviceWorker' in navigator)) {
    setWebPushEnabled(false)
    return
  }
  const reg = await navigator.serviceWorker.ready.catch(() => null)
  const sub = reg ? await getExistingSubscription(reg) : null
  if (sub) {
    try {
      await fetch(`${API}/push/subscribe`, {
        method: 'DELETE',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscription: sub.toJSON() }),
      })
    } catch {
      /* ignore */
    }
    try {
      await sub.unsubscribe()
    } catch {
      /* ignore */
    }
  }
  setWebPushEnabled(false)
}

/** Re-register an existing browser subscription with the server after login. */
export async function syncWebPushSubscription() {
  if (!isWebPushSupported() || !isWebPushEnabled()) return null
  if (notificationPermission() !== 'granted') {
    setWebPushEnabled(false)
    return null
  }
  const reg = await registerServiceWorker()
  if (!reg) return null
  const sub = await getExistingSubscription(reg)
  if (!sub) {
    setWebPushEnabled(false)
    return null
  }
  try {
    await postSubscription(sub, 'POST')
    return sub
  } catch {
    return null
  }
}

export function parseOpenChatFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search)
    if (params.get('open_chat') !== '1') return null
    const slot = params.get('slot')
    const userId = params.get('user_id')
    if (!slot || !userId) return null
    return { slot, user_id: Number(userId) || userId }
  } catch {
    return null
  }
}

export function clearOpenChatUrlParams() {
  try {
    const url = new URL(window.location.href)
    if (!url.searchParams.has('open_chat')) return
    url.searchParams.delete('open_chat')
    url.searchParams.delete('slot')
    url.searchParams.delete('user_id')
    window.history.replaceState({}, '', url.pathname + url.search + url.hash)
  } catch {
    /* ignore */
  }
}

export function subscribePushOpenChat(onOpen) {
  if (!('serviceWorker' in navigator) || typeof onOpen !== 'function') {
    return () => {}
  }
  const handler = (event) => {
    const data = event.data
    if (!data || data.type !== 'push-open-chat') return
    if (data.slot && data.user_id != null) {
      onOpen({ slot: data.slot, user_id: data.user_id })
    } else if (data.url) {
      window.location.href = data.url
    }
  }
  navigator.serviceWorker.addEventListener('message', handler)
  return () => navigator.serviceWorker.removeEventListener('message', handler)
}
