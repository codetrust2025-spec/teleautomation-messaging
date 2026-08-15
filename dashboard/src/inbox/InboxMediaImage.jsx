import React, { useEffect, useState } from 'react'
import { API } from '../config.js'
import { Spinner } from '../Loader.jsx'

export function InboxMediaImage({ slot, userId, messageId, alt = 'Photo' }) {
  const [failed, setFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [blobUrl, setBlobUrl] = useState('')

  const src = `${API}/inbox/${encodeURIComponent(slot)}/media/${Number(userId)}/${Number(messageId)}`

  useEffect(() => {
    let objectUrl = ''
    let cancelled = false
    setFailed(false)
    setLoaded(false)
    setBlobUrl('')

    async function load() {
      try {
        const res = await fetch(src, { credentials: 'include' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const type = (res.headers.get('content-type') || '').toLowerCase()
        if (type.includes('json') || type.includes('text/html')) {
          throw new Error('Not an image response')
        }
        const blob = await res.blob()
        if (!blob.size) throw new Error('Empty image')
        objectUrl = URL.createObjectURL(blob)
        if (cancelled) {
          URL.revokeObjectURL(objectUrl)
          return
        }
        setBlobUrl(objectUrl)
        setLoaded(true)
      } catch {
        if (!cancelled) setFailed(true)
      }
    }

    load()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [src])

  if (failed) {
    return (
      <div className="inbox-bubble-media-fallback" role="status">
        Photo could not load — tap <strong>refresh</strong> on the chat header to sync from Telegram.
      </div>
    )
  }

  return (
    <div className="inbox-bubble-image-wrap">
      {!loaded && (
        <div className="inbox-bubble-image-loading" aria-hidden>
          <Spinner size={18} />
        </div>
      )}
      {blobUrl ? (
        <img
          className="inbox-bubble-image"
          src={blobUrl}
          alt={alt}
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="inbox-bubble-image-loading" aria-hidden>
          <Spinner size={18} />
        </div>
      )}
    </div>
  )
}
