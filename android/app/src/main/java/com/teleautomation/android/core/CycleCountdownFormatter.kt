package com.teleautomation.android.core

/**
 * A cycle countdown decomposed into whole hours, minutes, and seconds.
 *
 * The component invariants are guaranteed by [CycleCountdownFormatter.format]:
 *  - `hours >= 0` (hours are *not* capped — a multi-day rest is rendered as e.g.
 *    `49:00:00`),
 *  - `0 <= minutes < 60`,
 *  - `0 <= seconds < 60`,
 *  - `hours * 3600 + minutes * 60 + seconds == floor(remainingMillis / 1000)`.
 *
 * The pre-rendered [label] is an `H+:MM:SS` string with the minutes and seconds
 * always two digits (e.g. `0:00:00`, `1:02:09`, `49:00:00`); hours use their
 * natural width since they are unbounded.
 */
data class CycleCountdown(
    val hours: Long,
    val minutes: Int,
    val seconds: Int,
    val label: String,
)

/**
 * Pure, device-independent formatter that turns remaining milliseconds until the
 * next fleet cycle into an hours/minutes/seconds countdown (R6.7).
 *
 * This logic lives in `core` (no Android, Compose, or Retrofit dependencies) so it
 * is unit/property testable on the plain JVM. The DashboardScreen's per-second
 * "sleeping between cycles" countdown (tasks plan 9.7) ticks by recomputing the
 * remaining milliseconds (`nextCycleEpochMillis - now`) and calling [format], so
 * the decomposition rule has a single source of truth. See the "Fleet / dashboard"
 * data model (`FleetState.nextCycleEpochMillis`) in the design document.
 *
 * Backing requirement:
 *  - R6.7: while the Fleet is sleeping between cycles, display a countdown to the
 *    next cycle as remaining time in hours, minutes, and seconds, updated at least
 *    once per second.
 *
 * Backing property (Property 7): for any non-negative remaining milliseconds `m`,
 * the formatted countdown yields hours `h`, minutes `mm`, seconds `ss` such that
 * `0 <= mm < 60`, `0 <= ss < 60`, and `h*3600 + mm*60 + ss == floor(m/1000)`.
 *
 * ### Behavior at the boundaries
 *  - `remainingMillis == 0` → `CycleCountdown(0, 0, 0, "0:00:00")`.
 *  - Sub-second remainders are truncated toward zero (floor of `m / 1000`), so any
 *    `m` in `0..999` formats as `0:00:00`. This matches a ticking clock that shows
 *    whole seconds remaining and never rounds up to a second that has not elapsed.
 *  - Large values are supported up to `Long.MAX_VALUE` milliseconds without
 *    overflow: seconds (`m / 1000`) fit in a `Long` and `hours` is derived from
 *    that same `Long`, so the hours component simply grows (it is never capped).
 *
 * ### Guarding negative input
 *  Negative remaining time is not a valid countdown. Callers that compute
 *  `nextCycleEpochMillis - now` can momentarily observe a negative value once the
 *  deadline has passed; they should clamp to zero (the cycle is over) rather than
 *  ask this formatter to render a negative duration. To make that contract
 *  explicit, [format] rejects negative input with [IllegalArgumentException]. Use
 *  [formatClamped] when the caller prefers to treat any already-elapsed deadline
 *  as `0:00:00`.
 */
object CycleCountdownFormatter {

    private const val MILLIS_PER_SECOND = 1_000L
    private const val SECONDS_PER_MINUTE = 60L
    private const val SECONDS_PER_HOUR = 3_600L

    /**
     * Decomposes [remainingMillis] into an hours/minutes/seconds [CycleCountdown].
     *
     * The whole-second count is `floor(remainingMillis / 1000)`; from it the
     * components are derived as `seconds = total % 60`, `minutes = (total / 60) %
     * 60`, and `hours = total / 3600`. This guarantees `0 <= minutes < 60`,
     * `0 <= seconds < 60`, and `hours*3600 + minutes*60 + seconds == total`.
     *
     * @param remainingMillis the non-negative milliseconds remaining until the next
     *   cycle; must be `>= 0`.
     * @return the decomposed countdown with a pre-rendered `H+:MM:SS` [CycleCountdown.label].
     * @throws IllegalArgumentException if [remainingMillis] is negative. See
     *   [formatClamped] for a non-throwing alternative.
     */
    fun format(remainingMillis: Long): CycleCountdown {
        require(remainingMillis >= 0) {
            "Remaining milliseconds must be >= 0, was $remainingMillis."
        }

        val totalSeconds = remainingMillis / MILLIS_PER_SECOND
        val hours = totalSeconds / SECONDS_PER_HOUR
        val minutes = ((totalSeconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE).toInt()
        val seconds = (totalSeconds % SECONDS_PER_MINUTE).toInt()

        val label = "$hours:${pad2(minutes)}:${pad2(seconds)}"
        return CycleCountdown(hours = hours, minutes = minutes, seconds = seconds, label = label)
    }

    /**
     * Like [format] but treats any negative [remainingMillis] as `0` (the cycle's
     * deadline has already passed), returning `0:00:00`. This is the convenient
     * entry point for the dashboard tick, which computes
     * `nextCycleEpochMillis - now` and can briefly see a negative value.
     */
    fun formatClamped(remainingMillis: Long): CycleCountdown =
        format(if (remainingMillis < 0) 0L else remainingMillis)

    /** Renders a non-negative component as a zero-padded two-digit string. */
    private fun pad2(value: Int): String = if (value < 10) "0$value" else value.toString()
}
