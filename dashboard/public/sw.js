/* TeleAutomation service worker — Web Push for PWA / iPhone Home Screen. */

self.addEventListener('install', (event) => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { title: 'TeleAutomation', body: event.data ? event.data.text() : 'New activity' }
  }

  const title = payload.title || 'TeleAutomation'
  const body = payload.body || 'New message'
  const url = payload.url || '/'
  const tag = payload.tag || 'inbox'
  const slot = payload.slot || null
  const userId = payload.user_id != null ? String(payload.user_id) : null

  event.waitUntil(
    // Deliberately NOT silent, unlike every in-page notification.
    //
    // A push can arrive when no tab is running — that is the whole point of it
    // on iOS/PWA. There is no Web Audio context alive to play the
    // TeleAutomation sound, so the operating system chime is the only audible
    // signal there is. Silencing it would trade a doubled sound in the rare
    // foreground case for total silence in the common background one.
    self.registration.showNotification(title, {
      body,
      tag,
      renotify: true,
      icon: '/favicon.svg',
      badge: '/favicon.svg',
      data: { url, slot, userId },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const data = event.notification.data || {}
  const url = data.url || '/'
  const slot = data.slot
  const userId = data.userId

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          client.postMessage({
            type: 'push-open-chat',
            slot,
            user_id: userId,
            url,
          })
          return client.focus()
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(url)
      }
      return undefined
    }),
  )
})

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'skip-waiting') {
    self.skipWaiting()
  }
})
