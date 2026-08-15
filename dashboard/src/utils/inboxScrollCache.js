/** In-memory scroll positions per conversation (session lifetime). */
const scrollByKey = new Map()

export function scrollCacheKey(slot, userId) {
  return `${slot}:${Number(userId)}`
}

export function getScrollTop(slot, userId) {
  return scrollByKey.get(scrollCacheKey(slot, userId))
}

export function setScrollTop(slot, userId, scrollTop) {
  if (scrollTop == null || Number.isNaN(scrollTop)) return
  scrollByKey.set(scrollCacheKey(slot, userId), Math.max(0, scrollTop))
}

export function clearScrollTop(slot, userId) {
  scrollByKey.delete(scrollCacheKey(slot, userId))
}
