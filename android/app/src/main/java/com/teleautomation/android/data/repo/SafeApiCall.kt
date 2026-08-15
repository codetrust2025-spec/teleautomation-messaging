package com.teleautomation.android.data.repo

import com.teleautomation.android.core.ConnectivityChecker
import com.teleautomation.android.core.ErrorKind
import com.teleautomation.android.core.NetworkErrorClassifier
import com.teleautomation.android.core.NetworkResult
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * Executes a Backend [call] and maps the outcome to a uniform [NetworkResult],
 * applying the centralized error classification so every repository behaves
 * consistently (R23.4, R23.5, R25, R26).
 *
 * Flow:
 *  1. Check connectivity first. If the device is offline the request is aborted
 *     without transmitting and an [ErrorKind.Offline] error is returned (R26.1).
 *  2. Otherwise invoke [call]. A successful, non-empty result becomes
 *     [NetworkResult.Success]; a result for which [isEmpty] holds becomes
 *     [NetworkResult.Empty] (R25.2).
 *  3. Any thrown failure is reduced to the three pure dimensions
 *     (connectivity / timeout / HTTP status) and classified by the pure
 *     [NetworkErrorClassifier] in `core`. The HTTP status is taken from Retrofit's
 *     [HttpException]; a timeout is detected via [NetworkErrorClassifier.isTimeoutError].
 *
 * Every returned [NetworkResult.Error] carries a [NetworkResult.Error.retry] closure
 * that re-invokes this same `safeApiCall` over the identical [call] closure, so the
 * operation is re-attempted with its original request parameters unchanged (R26.5,
 * R26.6). No local, cached-as-authoritative, or mock data is ever substituted for a
 * Backend response (R23.1, R23.4).
 *
 * [CancellationException] is rethrown so structured-concurrency cancellation is
 * never swallowed and misreported as an error.
 *
 * @param connectivity device-connectivity abstraction; checked before sending.
 * @param isEmpty predicate identifying an empty (zero-item) successful payload.
 * @param call the suspending Backend operation; closes over its original parameters.
 */
suspend fun <T> safeApiCall(
    connectivity: ConnectivityChecker,
    isEmpty: (T) -> Boolean = { false },
    call: suspend () -> T,
): NetworkResult<T> {
    if (!connectivity.isConnected()) {
        return NetworkResult.Error(
            kind = ErrorKind.Offline,
            message = messageFor(ErrorKind.Offline),
            retry = { safeApiCall(connectivity, isEmpty, call) },
        )
    }

    return try {
        val data = call()
        if (isEmpty(data)) NetworkResult.Empty else NetworkResult.Success(data)
    } catch (cancellation: CancellationException) {
        throw cancellation
    } catch (throwable: Throwable) {
        val httpStatus = (throwable as? HttpException)?.code()
        val kind = NetworkErrorClassifier.classify(
            isConnected = true,
            isTimeout = NetworkErrorClassifier.isTimeoutError(throwable),
            httpStatus = httpStatus,
        )
        NetworkResult.Error(
            kind = kind,
            message = messageFor(kind, throwable),
            retry = { safeApiCall(connectivity, isEmpty, call) },
            httpStatus = httpStatus,
        )
    }
}

/** Human-readable message for each [ErrorKind] surfaced to the affected view. */
private fun messageFor(kind: ErrorKind, throwable: Throwable? = null): String = when (kind) {
    ErrorKind.Offline -> "No network connectivity. Check your connection and retry."
    ErrorKind.Timeout -> "The request timed out. Please retry."
    ErrorKind.Server5xx -> "The server reported an error. Please retry."
    ErrorKind.Unauthorized -> "Your session is no longer valid. Please sign in again."
    ErrorKind.Client4xx -> "The request could not be completed."
    ErrorKind.Unknown -> throwable?.message ?: "Something went wrong. Please retry."
}
