package com.teleautomation.android.data.api

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Application-wide holder for authentication lifecycle signals.
 *
 * This is the Android analogue of the Web_App's global `auth:required` event
 * (`AuthContext.jsx`), which the web client dispatches whenever the Backend
 * returns a `401` for any request other than login/auth-status. Here it is a
 * single injectable singleton that the networking layer publishes to and the
 * auth layer / `AuthViewModel` (later tasks) collect from, so that an
 * unauthorized response anywhere in the app can drive a single, consistent
 * "clear session and route to Login" reaction (R2.6, R26.4).
 *
 * The [unauthorized] stream is a hot [SharedFlow] with no replay (a late
 * collector must not re-trigger a stale logout) but with a small buffer so an
 * emission from a non-suspending OkHttp interceptor thread is never dropped even
 * when there is momentarily no active collector.
 */
@Singleton
class AuthEvents @Inject constructor() {

    private val _unauthorized = MutableSharedFlow<Unit>(
        replay = 0,
        extraBufferCapacity = 1,
    )

    /**
     * Emits exactly once per observed unauthorized (`401`) signal. Collected by
     * the auth layer to clear the stored [com.teleautomation.android.data.local.Session]
     * state and navigate to the login screen.
     */
    val unauthorized: SharedFlow<Unit> = _unauthorized.asSharedFlow()

    /**
     * Publishes an unauthorized signal. Safe to call from a non-suspending
     * context (e.g. an OkHttp interceptor thread); the buffered [SharedFlow]
     * accepts the emission without blocking and without losing it when no
     * collector is currently active.
     */
    fun notifyUnauthorized() {
        _unauthorized.tryEmit(Unit)
    }
}
