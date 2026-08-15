package com.teleautomation.android.core

import java.io.InterruptedIOException
import java.net.SocketTimeoutException

/**
 * Pure, device-independent classification of a Backend request outcome into exactly
 * one [ErrorKind] (R23.4, R23.5, R26.1–R26.4).
 *
 * This logic lives in `core` (no Android, OkHttp, or Retrofit dependencies) so it is
 * unit/property testable on the plain JVM. The data layer's `safeApiCall` performs
 * the actual call and connectivity check, reduces the outcome to the three pure
 * dimensions below, and delegates here for the single source-of-truth mapping.
 *
 * Backing property (Property 31): for any request outcome described by connectivity,
 * exception, and HTTP status, the classifier yields exactly one [ErrorKind] per the
 * rules — no connectivity → [ErrorKind.Offline]; no response within the timeout →
 * [ErrorKind.Timeout]; HTTP 5xx → [ErrorKind.Server5xx]; HTTP 401 →
 * [ErrorKind.Unauthorized]; other 4xx → [ErrorKind.Client4xx]; parse/other →
 * [ErrorKind.Unknown].
 */
object NetworkErrorClassifier {

    /**
     * Maps a failed request outcome to exactly one [ErrorKind].
     *
     * The dimensions are evaluated in priority order so the result is deterministic
     * and total over every input combination:
     *  1. [isConnected] `false` → [ErrorKind.Offline] (checked before transmitting,
     *     R26.1). Connectivity dominates so an offline attempt is never reported as a
     *     timeout or HTTP error.
     *  2. [isTimeout] `true` → [ErrorKind.Timeout] (no complete response in time,
     *     R26.2, R23.5).
     *  3. [httpStatus] present → classified by range: `500..599` →
     *     [ErrorKind.Server5xx] (R26.3); exactly `401` → [ErrorKind.Unauthorized]
     *     (R26.4); any other `400..499` → [ErrorKind.Client4xx] (R4.6, R1.8); any
     *     other status code → [ErrorKind.Unknown].
     *  4. Otherwise (e.g. a parse error or an unclassified exception with no status)
     *     → [ErrorKind.Unknown].
     *
     * @param isConnected whether the device reported network connectivity before the
     *   request was sent.
     * @param isTimeout whether the request failed because no complete response
     *   arrived within the timeout window.
     * @param httpStatus the HTTP status code if the Backend produced a response,
     *   or `null` when the failure was not an HTTP error (no response, parse error).
     */
    fun classify(isConnected: Boolean, isTimeout: Boolean, httpStatus: Int?): ErrorKind {
        if (!isConnected) return ErrorKind.Offline
        if (isTimeout) return ErrorKind.Timeout
        if (httpStatus != null) {
            return when {
                httpStatus in 500..599 -> ErrorKind.Server5xx
                httpStatus == 401 -> ErrorKind.Unauthorized
                httpStatus in 400..499 -> ErrorKind.Client4xx
                else -> ErrorKind.Unknown
            }
        }
        return ErrorKind.Unknown
    }

    /**
     * Pure predicate identifying a Backend HTTP 403 Forbidden response.
     *
     * [classify] folds every non-401 4xx into [ErrorKind.Client4xx], which is the
     * correct view-state bucket; this helper recovers the specific 403 case from the
     * retained status code so fleet-control actions can surface an authorization
     * error and leave local state unchanged (R4.6) without altering the broader
     * classification taxonomy.
     *
     * @param httpStatus the HTTP status code, or `null` when the failure was not an
     *   HTTP error. Only an exact `403` is forbidden.
     */
    fun isForbidden(httpStatus: Int?): Boolean = httpStatus == 403

    /**
     * Pure predicate identifying a timeout failure from a thrown [throwable].
     *
     * Recognises [SocketTimeoutException] and the broader [InterruptedIOException]
     * (which OkHttp raises when a call/connect/read deadline is exceeded). Both are
     * plain-JVM types, keeping this helper free of Android/network dependencies so it
     * can be exercised alongside [classify].
     */
    fun isTimeoutError(throwable: Throwable?): Boolean =
        throwable is SocketTimeoutException || throwable is InterruptedIOException
}
