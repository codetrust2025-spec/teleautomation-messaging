import React, { useEffect, useState } from 'react'
import { API } from '../config.js'
import { Spinner } from '../Loader.jsx'

function kindFromMime(mediaKind, mime) {
  const type = (mime || '').toLowerCase()
  if (mediaKind === 'sticker' || mediaKind === 'photo') return 'image'
  if (type.startsWith('video/') || mediaKind === 'video') return 'video'
  if (type.startsWith('audio/') || mediaKind === 'voice' || mediaKind === 'audio') return 'audio'
  if (type.startsWith('image/')) return 'image'
  if (type === 'application/pdf' || type.includes('pdf')) return 'pdf'
  if (
    mediaKind === 'document'
    || type.startsWith('application/')
    || type.includes('octet-stream')
  ) {
    return 'document'
  }
  return 'image'
}

export function InboxMediaAttachment({
  slot,
  userId,
  messageId,
  mediaKind = 'photo',
  alt = 'Attachment',
  fileName = 'Document',
  mediaSrc = null,
}) {
  const [failed, setFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [blobUrl, setBlobUrl] = useState('')
  const [playKind, setPlayKind] = useState('image')

  const src = mediaSrc || `${API}/inbox/${encodeURIComponent(slot)}/media/${Number(userId)}/${Number(messageId)}`
  const downloadName = fileName && fileName !== 'Document' ? fileName : `document-${messageId}`

  useEffect(() => {
    let objectUrl = ''
    let cancelled = false
    setFailed(false)
    setLoaded(false)
    setBlobUrl('')
    setPlayKind(kindFromMime(mediaKind, ''))

    async function load() {
      try {
        const res = await fetch(src, { credentials: 'include' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const type = (res.headers.get('content-type') || '').toLowerCase()
        if (type.includes('json') || type.includes('text/html')) {
          throw new Error('Not a media response')
        }
        const blob = await res.blob()
        if (!blob.size) throw new Error('Empty media')
        let kind = kindFromMime(mediaKind, type)
        if (
          (mediaKind === 'document' || mediaKind === 'media')
          && kind === 'image'
          && !type.startsWith('image/')
        ) {
          kind = 'document'
        }
        objectUrl = URL.createObjectURL(blob)
        if (cancelled) {
          URL.revokeObjectURL(objectUrl)
          return
        }
        setPlayKind(kind)
        setBlobUrl(objectUrl)
        if (kind === 'document' || kind === 'pdf' || kind === 'audio') {
          setLoaded(true)
        }
      } catch {
        if (!cancelled) setFailed(true)
      }
    }

    load()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [src, mediaKind])

  if (failed) {
    const label = mediaKind === 'video'
      ? 'Video'
      : mediaKind === 'document'
        ? 'Document'
        : mediaKind === 'voice'
          ? 'Voice'
          : mediaKind === 'sticker'
            ? 'Sticker'
            : 'Media'
    const hint = mediaKind === 'sticker'
      ? 'Animated stickers need a sync first.'
      : `${label} could not load.`
    return (
      <div className="inbox-bubble-media-fallback" role="status">
        {hint} Use <strong>Sync from Telegram</strong> in the chat menu (⋮).
      </div>
    )
  }

  const isFile = playKind === 'document' || playKind === 'pdf'

  return (
    <div className={`inbox-bubble-media-wrap inbox-bubble-media-wrap--${playKind}`}>
      {!loaded && (
        <div className="inbox-bubble-image-loading" aria-hidden>
          <Spinner size={18} />
        </div>
      )}
      {blobUrl && playKind === 'video' && (
        <video
          className="inbox-bubble-video"
          src={blobUrl}
          controls
          playsInline
          preload="metadata"
          onLoadedData={() => setLoaded(true)}
          onError={() => setFailed(true)}
        >
          <track kind="captions" />
        </video>
      )}
      {blobUrl && playKind === 'audio' && (
        <audio
          className="inbox-bubble-audio"
          src={blobUrl}
          controls
          preload="metadata"
          onLoadedData={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      )}
      {blobUrl && playKind === 'image' && (
        <img
          className="inbox-bubble-image"
          src={blobUrl}
          alt={alt}
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      )}
      {blobUrl && isFile && (
        <div className="inbox-bubble-document">
          {playKind === 'pdf' && (
            <iframe
              className="inbox-bubble-pdf"
              src={blobUrl}
              title={downloadName}
              onLoad={() => setLoaded(true)}
            />
          )}
          <div className="inbox-bubble-document-row">
            <span className="inbox-bubble-document-icon" aria-hidden>📄</span>
            <span className="inbox-bubble-document-name" title={downloadName}>
              {downloadName}
            </span>
          </div>
          <div className="inbox-bubble-document-actions">
            <a
              className="inbox-bubble-document-btn"
              href={blobUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open
            </a>
            <a
              className="inbox-bubble-document-btn inbox-bubble-document-btn--secondary"
              href={blobUrl}
              download={downloadName}
            >
              Download
            </a>
          </div>
        </div>
      )}
      {!blobUrl && !isFile && (
        <div className="inbox-bubble-image-loading" aria-hidden>
          <Spinner size={18} />
        </div>
      )}
    </div>
  )
}
