package com.teleautomation.android.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Kotlinx-serializable DTOs for the Backend `/auth/*` routes.
 *
 * Field names mirror the Backend JSON exactly (verified against
 * `core/dashboard_auth_api.py`); snake_case wire names are bound with
 * [SerialName] so the Kotlin side stays idiomatic camelCase. All DTOs declare
 * defaults so the lenient JSON converter (unknown keys ignored, missing values
 * coerced) keeps deserializing as the Backend evolves (R22.3).
 *
 * No new endpoints are introduced — every shape here maps 1:1 to a route the
 * Web_App already calls (R23.2).
 */

/**
 * Response of `GET /auth/status`.
 *
 * Shape: `{ enabled, authenticated, username, role, reference }`.
 *
 * [role] is decoded via the [Role] `@SerialName` tokens (`"admin"`/`"handler"`);
 * an absent or unrecognized value coerces to [Role.ADMIN], matching the Web_App
 * default (R1.1, R2.1).
 */
@Serializable
data class AuthStatus(
    val enabled: Boolean = false,
    val authenticated: Boolean = false,
    val username: String? = null,
    val role: Role = Role.ADMIN,
    val reference: String? = null,
)

/** Request body for `POST /auth/login`: `{ username, password }` (R1.6). */
@Serializable
data class LoginRequest(
    val username: String,
    val password: String,
)

/**
 * Response of a successful `POST /auth/login`.
 *
 * Shape: `{ status: "ok", username, role, reference }`. When Backend auth is
 * disabled the response omits `status` and returns `{ username, role, reference }`;
 * both forms decode here. The session cookie itself is captured by the OkHttp
 * cookie jar, not this body (R1.7).
 */
@Serializable
data class LoginResponse(
    val status: String? = null,
    val username: String? = null,
    val role: Role = Role.ADMIN,
    val reference: String? = null,
)

/** Response of `POST /auth/logout`: `{ status: "ok" }` (R2.4). */
@Serializable
data class LogoutResponse(
    val status: String? = null,
)

/**
 * Request body for `POST /auth/change-password`:
 * `{ current_password, new_password }` (R3.5).
 */
@Serializable
data class ChangePasswordRequest(
    @SerialName("current_password") val currentPassword: String,
    @SerialName("new_password") val newPassword: String,
)

/** Response of `POST /auth/change-password`: `{ status: "ok" }` on success (R3.6). */
@Serializable
data class ChangePasswordResponse(
    val status: String? = null,
)

/**
 * Request body for `POST /auth/reset-password` (Handler self-service reset):
 * `{ username, reference, new_password }` (R3.2).
 */
@Serializable
data class ResetPasswordRequest(
    val username: String,
    val reference: String,
    @SerialName("new_password") val newPassword: String,
)

/** Response of `POST /auth/reset-password`: `{ status: "ok" }` on success (R3.3). */
@Serializable
data class ResetPasswordResponse(
    val status: String? = null,
)
