package com.teleautomation.android.core

import kotlin.math.roundToInt

/**
 * Pure, device-independent success-rate computation for the fleet dashboard
 * (R6.1, Property 6).
 *
 * The dashboard reports the percentage of posts that were sent successfully out of
 * the total posts attempted. "Attempted" excludes groups that were skipped because
 * they had already been posted to — those were never send attempts — which mirrors
 * the Web_App reference (`dashboard/src/utils/globalStats.js` `computeSuccessRatePct`,
 * where `attempted = success + failed`). The Android side therefore passes
 * `postsAttempted = postsSent + postsFailed`; see [FleetState][com.teleautomation.android.data.api.FleetState].
 *
 * This object lives in `core` (no Android / Retrofit / coroutine dependencies) so
 * the computation can be unit/property tested on the plain JVM (task 9.2).
 *
 * Backing property (Property 6): for any non-negative posts-sent `s` and
 * posts-attempted `a` with `s ≤ a`, the result equals `round(s / a * 100)` and lies
 * within `[0, 100]`; when `a ≤ 0` the result is `0`.
 */
object SuccessRate {

    /** The inclusive lower bound of a percentage. */
    private const val MIN_PERCENT = 0

    /** The inclusive upper bound of a percentage. */
    private const val MAX_PERCENT = 100

    /**
     * Computes the integer success-rate percentage for [postsSent] successful posts
     * out of [postsAttempted] attempts (R6.1, Property 6).
     *
     * Rules:
     *  - When [postsAttempted] is `0` (or negative — never expected) the rate is `0`,
     *    representing "no attempts yet" as a concrete display value rather than an
     *    undefined division.
     *  - Otherwise the rate is `round(postsSent / postsAttempted * 100)`, then
     *    clamped into `[0, 100]` so that malformed inputs (for example a Backend
     *    payload where `postsSent > postsAttempted`) can never render an
     *    out-of-range percentage.
     *
     * Computation is done in [Double] to keep the rounding well-defined, and the
     * clamp guarantees the post-condition regardless of input.
     *
     * @param postsSent number of posts sent successfully (`s`).
     * @param postsAttempted number of posts attempted (`a`, i.e. `success + failed`).
     * @return the success rate as an integer percentage in `[0, 100]`.
     */
    fun percent(postsSent: Int, postsAttempted: Int): Int {
        if (postsAttempted <= 0) return MIN_PERCENT
        val pct = (postsSent.toDouble() / postsAttempted.toDouble()) * 100.0
        return pct.roundToInt().coerceIn(MIN_PERCENT, MAX_PERCENT)
    }
}
