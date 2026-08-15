package com.teleautomation.android.core

import kotlin.time.Duration
import kotlin.time.Duration.Companion.milliseconds
import kotlin.time.Duration.Companion.seconds

/**
 * Pure, device-independent reconnect-backoff schedule for the realtime WebSocket
 * client (R22.4).
 *
 * This logic lives in `core` (no Android, OkHttp, or Retrofit dependencies) so it
 * is unit/property testable on the plain JVM. `RealtimeClient` (tasks plan 4.5)
 * delegates to it to compute the delay before each reconnect attempt; see the
 * "RealtimeClient" section of the design document.
 *
 * Backing requirement (R22.4): on connection close or failure the client
 * reconnects using exponential backoff that starts at 1 second, doubles each
 * attempt, and is capped at 30 seconds.
 *
 * Backing property (Property 27): for any attempt index `k >= 0` the delay equals
 * `min(30s, 1s * 2^k)`; the resulting sequence is monotonically non-decreasing and
 * never exceeds 30 seconds.
 */
object ReconnectBackoffPolicy {

    /** The base delay used for the first reconnect attempt (`k == 0`), in milliseconds. */
    const val BASE_DELAY_MILLIS: Long = 1_000L

    /** The maximum reconnect delay; the schedule is capped here (R22.4), in milliseconds. */
    const val MAX_DELAY_MILLIS: Long = 30_000L

    /** [BASE_DELAY_MILLIS] expressed as a [Duration]. */
    val BASE_DELAY: Duration = 1.seconds

    /** [MAX_DELAY_MILLIS] expressed as a [Duration]. */
    val MAX_DELAY: Duration = 30.seconds

    /**
     * The smallest attempt index at which `BASE_DELAY_MILLIS * 2^k` reaches or
     * exceeds [MAX_DELAY_MILLIS]. For every attempt at or beyond this index the
     * delay is the constant cap, so the doubling shift is never evaluated for an
     * exponent this large — which is what guards against integer overflow when
     * `k` is arbitrarily big.
     */
    private val CAP_ATTEMPT: Int = run {
        var k = 0
        // Safe: the loop stops well before the shift could overflow a Long because
        // BASE_DELAY_MILLIS << k crosses MAX_DELAY_MILLIS after only a few doublings.
        while ((BASE_DELAY_MILLIS shl k) < MAX_DELAY_MILLIS) {
            k++
        }
        k
    }

    /**
     * Returns the reconnect delay for the given zero-based [attempt] index as
     * `min(30s, 1s * 2^attempt)`.
     *
     * The exponent is capped at [CAP_ATTEMPT] before the doubling shift is
     * evaluated, so large [attempt] values return the [MAX_DELAY] cap directly
     * without ever computing a shift that could overflow. The returned sequence
     * is monotonically non-decreasing and never exceeds [MAX_DELAY] (R22.4,
     * Property 27).
     *
     * @param attempt the zero-based reconnect attempt index; must be `>= 0`.
     * @throws IllegalArgumentException if [attempt] is negative.
     */
    fun backoffDelay(attempt: Int): Duration {
        require(attempt >= 0) { "Reconnect attempt index must be >= 0, was $attempt." }

        if (attempt >= CAP_ATTEMPT) {
            return MAX_DELAY
        }

        // attempt < CAP_ATTEMPT guarantees the shift stays below MAX_DELAY_MILLIS,
        // so this can neither exceed the cap nor overflow a Long.
        val candidateMillis = BASE_DELAY_MILLIS shl attempt
        return minOf(MAX_DELAY_MILLIS, candidateMillis).milliseconds
    }
}
