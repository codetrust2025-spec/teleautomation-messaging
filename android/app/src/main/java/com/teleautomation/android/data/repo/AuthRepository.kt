package com.teleautomation.android.data.repo

import com.teleautomation.android.core.ConnectivityChecker
import com.teleautomation.android.core.NetworkResult
import com.teleautomation.android.data.api.AuthApiService
import com.teleautomation.android.data.api.AuthStatus
import com.teleautomation.android.data.api.ChangePasswordRequest
import com.teleautomation.android.data.api.ChangePasswordResponse
import com.teleautomation.android.data.api.LoginRequest
import com.teleautomation.android.data.api.LoginResponse
import com.teleautomation.android.data.api.LogoutResponse
import com.teleautomation.android.data.api.ResetPasswordRequest
import com.teleautomation.android.data.api.ResetPasswordResponse
import com.teleautomation.android.data.local.SessionStore
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for Operator authentication, session, and password management
 * (R1, R2, R3).
 *
 * Wraps [AuthApiService] through [safeApiCall] so every method returns the uniform
 * [NetworkResult] with a retry closure capturing the original parameters
 * (R25, R26). The Backend session cookie is persisted automatically by the OkHttp
 * encrypted cookie jar; this repository additionally records the **identity**
 * (username, [com.teleautomation.android.data.api.Role], handler reference) in the
 * encrypted [SessionStore] on a successful login or status check (R2.1, R2.7), and
 * clears all stored session state on logout (R2.4, R2.5).
 *
 * Identity persistence is performed inside the executed call so the retry closure
 * reproduces it exactly when a retried attempt succeeds.
 *
 * The [AuthViewModel][com.teleautomation.android.presentation] (task 6.6) consumes
 * these methods to drive the startup auth-gate, login, logout, and the
 * change/reset-password flows; this layer performs no navigation or timeout policy.
 */
@Singleton
class AuthRepository @Inject constructor(
    private val authApi: AuthApiService,
    private val sessionStore: SessionStore,
    private val connectivity: ConnectivityChecker,
) {

    /**
     * Fetches the current session/identity from `GET /auth/status` (R1.1, R2.1).
     *
     * On a successful, authenticated response the identity is persisted to
     * [SessionStore] so the navigation area can show the username (R2.7) and the
     * role-based shell can resolve immediately on next launch. A non-authenticated
     * response is returned unchanged; clearing an invalid session is the caller's
     * responsibility (R2.2, handled by the auth-gate in task 6.6).
     */
    suspend fun status(): NetworkResult<AuthStatus> =
        safeApiCall(connectivity) {
            authApi.status().also { status ->
                if (status.authenticated) {
                    sessionStore.saveIdentity(status.username, status.role, status.reference)
                }
            }
        }

    /**
     * Submits credentials to `POST /auth/login` (R1.6, R1.7).
     *
     * On success the session cookie is captured by the cookie jar and the returned
     * identity is persisted to [SessionStore]. An authentication failure surfaces as
     * a [NetworkResult.Error] (HTTP 401 → [com.teleautomation.android.core.ErrorKind.Unauthorized])
     * carrying the Backend message and no session is stored (R1.8).
     *
     * Callers must enforce the non-empty username/password gate (Property 1, task
     * 6.2) before invoking this method.
     */
    suspend fun login(username: String, password: String): NetworkResult<LoginResponse> =
        safeApiCall(connectivity) {
            authApi.login(LoginRequest(username = username, password = password)).also { resp ->
                sessionStore.saveIdentity(resp.username, resp.role, resp.reference)
            }
        }

    /**
     * Calls `POST /auth/logout` and clears all locally stored session state
     * (cookies + identity) regardless of the Backend outcome, so signing out always
     * returns the app to the unauthenticated state (R2.4, R2.5).
     */
    suspend fun logout(): NetworkResult<LogoutResponse> {
        val result = safeApiCall(connectivity) { authApi.logout() }
        sessionStore.clear()
        return result
    }

    /**
     * Submits the current and new password to `POST /auth/change-password` for the
     * authenticated Operator (R3.5, R3.6). Caller enforces the `[8,128]` length
     * bounds (Property 2, task 6.4) before calling.
     */
    suspend fun changePassword(
        currentPassword: String,
        newPassword: String,
    ): NetworkResult<ChangePasswordResponse> =
        safeApiCall(connectivity) {
            authApi.changePassword(
                ChangePasswordRequest(
                    currentPassword = currentPassword,
                    newPassword = newPassword,
                ),
            )
        }

    /**
     * Submits a Handler self-service reset to `POST /auth/reset-password` using the
     * username, handler reference, and new password (R3.2, R3.3).
     */
    suspend fun resetPassword(
        username: String,
        reference: String,
        newPassword: String,
    ): NetworkResult<ResetPasswordResponse> =
        safeApiCall(connectivity) {
            authApi.resetPassword(
                ResetPasswordRequest(
                    username = username,
                    reference = reference,
                    newPassword = newPassword,
                ),
            )
        }
}
