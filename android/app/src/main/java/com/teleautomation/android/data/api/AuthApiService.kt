package com.teleautomation.android.data.api

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

/**
 * Retrofit interface for the Backend `/auth/*` routes.
 *
 * Maps 1:1 to the existing FastAPI endpoints in `core/dashboard_auth_api.py`
 * (no new or mock endpoints, R23.2). Paths are relative; the effective origin is
 * supplied per request by the dynamic base-URL interceptor and the session cookie
 * is attached automatically by the encrypted cookie jar (R23.3).
 *
 * Created from the shared Retrofit instance via Hilt (`ApiModule`). Each function
 * is `suspend` so callers run on the IO dispatcher inside structured concurrency;
 * `safeApiCall` in the repository layer maps thrown HTTP/transport failures to a
 * uniform `NetworkResult`.
 */
interface AuthApiService {

    /** `GET /auth/status` — current session/identity (R1.1, R2.1). */
    @GET("auth/status")
    suspend fun status(): AuthStatus

    /** `POST /auth/login` — exchange credentials for a session cookie (R1.6, R1.7). */
    @POST("auth/login")
    suspend fun login(@Body request: LoginRequest): LoginResponse

    /** `POST /auth/logout` — invalidate the current session (R2.4). */
    @POST("auth/logout")
    suspend fun logout(): LogoutResponse

    /** `POST /auth/change-password` — authenticated self password change (R3.5, R3.6). */
    @POST("auth/change-password")
    suspend fun changePassword(@Body request: ChangePasswordRequest): ChangePasswordResponse

    /** `POST /auth/reset-password` — Handler self-service reset (R3.2, R3.3). */
    @POST("auth/reset-password")
    suspend fun resetPassword(@Body request: ResetPasswordRequest): ResetPasswordResponse
}
