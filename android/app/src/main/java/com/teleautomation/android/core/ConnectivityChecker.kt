package com.teleautomation.android.core

/**
 * Abstraction over the device's current network-connectivity status (R26.1).
 *
 * Declared in `core` with no Android dependency so the offline branch of
 * `safeApiCall` is testable with a trivial fake (returning `false` / `true`) on the
 * plain JVM. The production Android implementation backed by `ConnectivityManager`
 * lives in the data layer.
 */
fun interface ConnectivityChecker {

    /**
     * @return `true` when the device currently has network connectivity capable of
     *   reaching the Backend; `false` when offline. When `false`, `safeApiCall`
     *   aborts the request without transmitting it and returns
     *   [ErrorKind.Offline][com.teleautomation.android.core.ErrorKind.Offline]
     *   (R26.1).
     */
    fun isConnected(): Boolean
}
