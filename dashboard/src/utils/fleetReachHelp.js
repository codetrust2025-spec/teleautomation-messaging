/** Tooltip copy for all-accounts today reach metrics (Forwarding tab). */

export const FORWARDING_METRIC_HELP = {
  forwardPosts:
    'Cumulative successful posts to joined groups since Reset 24 Hours. Persists across ticks and refresh. Compare with “Current tick sent” for live batch progress.',
  runningNow:
    'How many accounts are actively forwarding right now (24/7 loop or a forward job). 0 = all stopped or resting between ticks.',
  currentTickSent:
    'Live batch only — resets when a new forward tick starts. Sent = successes this tick; skipped = already posted there; failed = errors. Not the same as “Forward posts (since reset)”.',
  currentTickAccount:
    'This account’s current forward batch only. Sent / skipped / failed apply to the active tick, not since reset.',
  joinedSinceReset:
    'New groups joined by automation since Reset 24 Hours (not messages sent). The limit is the shared daily join cap (sum of per-account limits). Resets with Reset 24 Hours.',
  joinedSinceResetAccount:
    'New groups this account joined since Reset 24 Hours. Limit is this account’s daily join cap.',
}
