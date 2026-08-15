package com.teleautomation.android.core

/**
 * The kind of failure surfaced by a Backend call, used to drive the transient-state
 * UI (R25) and network-resilience handling (R26).
 *
 * Exactly one [ErrorKind] is assigned to any failed outcome by the pure
 * [NetworkErrorClassifier], per the design's single-source-of-truth classification
 * table:
 *  - [Offline]      — no device connectivity before the request is sent (R26.1).
 *  - [Timeout]      — no complete response within the timeout window (R26.2, R23.5).
 *  - [Server5xx]    — the Backend returned an HTTP 5xx server error (R26.3).
 *  - [Unauthorized] — the Backend returned HTTP 401 (R2.6, R26.4).
 *  - [Client4xx]    — any other HTTP 4xx, including 403 on fleet actions (R4.6, R1.8).
 *  - [Unknown]      — a parse error or any other unclassified failure.
 */
enum class ErrorKind {
    Offline,
    Timeout,
    Server5xx,
    Unauthorized,
    Client4xx,
    Unknown,
}

/**
 * Uniform result type returned by repositories for any Backend operation (R25, R26).
 *
 * `Loading | Success(data) | Empty | Error(kind, message, retry)`.
 *
 * Every [Error] carries a [retry][Error.retry] closure that captures the original
 * request parameters so the same operation can be re-attempted unchanged (R26.5,
 * R26.6). The closure re-issues the operation and yields a fresh [NetworkResult].
 *
 * This type lives in `core` (no Android/OkHttp/Retrofit dependencies) so the result
 * shape and the classifier that produces it are unit/property testable on the plain
 * JVM. The actual call execution and connectivity check live in the data layer's
 * `safeApiCall`, which delegates classification here.
 */
sealed interface NetworkResult<out T> {

    /** The request is in progress. */
    data object Loading : NetworkResult<Nothing>

    /** The request succeeded and produced [data]. */
    data class Success<out T>(val data: T) : NetworkResult<T>

    /** The request succeeded but produced no items (empty result set, R25.2). */
    data object Empty : NetworkResult<Nothing>

    /**
     * The request failed.
     *
     * @param kind the single [ErrorKind] assigned by [NetworkErrorClassifier].
     * @param message a human-readable description for the affected view.
     * @param retry re-issues the same operation with the original parameters and
     *   returns a fresh [NetworkResult] (R26.5, R26.6).
     * @param httpStatus the HTTP status code when the failure was an HTTP error, or
     *   `null` otherwise (offline, timeout, parse/unknown). [ErrorKind.Client4xx]
     *   covers every non-401 4xx, so this retains the exact code for the cases that
     *   must be distinguished further — notably HTTP 403 on fleet-control actions
     *   (R4.6), detected via [NetworkErrorClassifier.isForbidden].
     */
    data class Error<out T>(
        val kind: ErrorKind,
        val message: String,
        val retry: suspend () -> NetworkResult<T>,
        val httpStatus: Int? = null,
    ) : NetworkResult<T>
}
