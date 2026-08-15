const HOUR_MS = 3600 * 1000

function parseLogTs(entry) {
  const raw = entry?.timestamp || entry?.time
  if (!raw) return null
  const t = Date.parse(raw)
  return Number.isFinite(t) ? t : null
}

function isLogSuccess(entry) {
  const event = String(entry?.event || '').toUpperCase()
  const action = String(entry?.action || '').toLowerCase()
  const level = String(entry?.level || '').toLowerCase()
  if (event === 'SEND_SUCCESS' || action === 'sent' || action === 'ok') return true
  if (level === 'success') return true
  const text = String(entry?.summary || entry?.fields?.detail || entry?.msg || '').toLowerCase()
  return text.includes('message sent') || text.includes('forwarded to')
}

function isLogFailure(entry) {
  const event = String(entry?.event || '').toUpperCase()
  const action = String(entry?.action || '').toLowerCase()
  const level = String(entry?.level || '').toLowerCase()
  if (event === 'SEND_FAIL' || action === 'failed') return true
  if (level === 'error') {
    const text = String(entry?.summary || entry?.fields?.detail || entry?.msg || '').toLowerCase()
    return text.includes('fail') || text.includes('cannot post') || text.includes('flood')
  }
  return false
}

/** Bucket structured logs into hourly success/fail counts (best-effort for failed sends). */
export function bucketLogsByHour(logs, bucketCount = 24, nowMs = Date.now()) {
  const sent = Array(bucketCount).fill(0)
  const failed = Array(bucketCount).fill(0)
  for (const entry of logs || []) {
    const ts = parseLogTs(entry)
    if (ts == null) continue
    const ageMs = nowMs - ts
    if (ageMs < 0 || ageMs >= bucketCount * HOUR_MS) continue
    const idx = bucketCount - 1 - Math.floor(ageMs / HOUR_MS)
    if (idx < 0 || idx >= bucketCount) continue
    if (isLogSuccess(entry)) sent[idx] += 1
    else if (isLogFailure(entry)) failed[idx] += 1
  }
  return { sent, failed }
}

function pickHourlySent(dailyStats, modeFilter) {
  const hourly = dailyStats?.hourly
  const sent = hourly?.sent
  if (!sent) return null
  if (modeFilter === 'forwarding') return sent.forward || sent.all
  if (modeFilter === 'campaign') return sent.campaign || sent.all
  return sent.all
}

function successRatesFromBuckets(sent, failed) {
  return sent.map((s, i) => {
    const attempts = s + (failed[i] || 0)
    if (attempts <= 0) return null
    return Math.round((s / attempts) * 1000) / 10
  })
}

/**
 * Build chart-ready hourly series for the desktop performance panel.
 * Prefers backend send_history buckets; merges log-derived failures for success rate.
 */
export function buildDeskPerformanceSeries({
  dailyStats,
  logs = [],
  modeFilter = 'all',
  bucketCount = 24,
}) {
  const labels = dailyStats?.hourly?.labels || Array.from({ length: bucketCount }, (_, i) => {
    const age = bucketCount - 1 - i
    return age === 0 ? 'now' : age % 6 === 0 ? `-${age}h` : ''
  })

  const backendSent = pickHourlySent(dailyStats, modeFilter)
  const logBuckets = bucketLogsByHour(logs, bucketCount)

  const sent = backendSent
    ? [...backendSent]
    : [...logBuckets.sent]

  const failed = [...logBuckets.failed]
  const usesBackendHistory = Array.isArray(backendSent)
  // Success rate must use one source — logs for both axes when volume comes from backend history.
  const rateSent = usesBackendHistory ? logBuckets.sent : sent
  const rateFailed = failed
  const successRate = successRatesFromBuckets(rateSent, rateFailed)
  const totalSent = sent.reduce((a, b) => a + b, 0)
  const totalFailed = failed.reduce((a, b) => a + b, 0)
  const hasData = totalSent > 0 || totalFailed > 0

  return {
    labels,
    sent,
    failed,
    successRate,
    totalSent,
    totalFailed,
    hasData,
    usesBackendHistory,
  }
}

export function chartPathFromValues(values, width, height, padX, padY, maxValue) {
  const max = Math.max(maxValue, 1)
  const innerW = width - padX * 2
  const innerH = height - padY * 2
  const step = innerW / Math.max(values.length - 1, 1)
  const points = values.map((v, i) => {
    const x = padX + i * step
    const y = padY + innerH - (Math.max(0, Number(v) || 0) / max) * innerH
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return points.join(' ')
}

export function chartAreaPath(values, width, height, padX, padY, maxValue) {
  const max = Math.max(maxValue, 1)
  const innerW = width - padX * 2
  const innerH = height - padY * 2
  const step = innerW / Math.max(values.length - 1, 1)
  const baseline = padY + innerH
  let d = `M ${padX} ${baseline}`
  values.forEach((v, i) => {
    const x = padX + i * step
    const y = padY + innerH - (Math.max(0, Number(v) || 0) / max) * innerH
    d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`
  })
  d += ` L ${padX + innerW} ${baseline} Z`
  return d
}
