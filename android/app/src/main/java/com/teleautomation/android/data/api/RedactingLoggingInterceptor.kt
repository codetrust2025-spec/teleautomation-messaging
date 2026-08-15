package com.teleautomation.android.data.api

import com.teleautomation.android.BuildConfig
import okhttp3.Interceptor
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import javax.inject.Inject
import javax.inject.Singleton

/**
 * HTTP logging that never writes secrets to the log (Security: "No
 * cleartext-secret logging").
 *
 * Two safeguards are applied:
 *
 * 1. **Header redaction (always).** `Cookie`, `Set-Cookie`, and `Authorization`
 *    headers are redacted on every request/response, so the session cookie is
 *    never printed regardless of endpoint.
 *
 * 2. **Body redaction for sensitive endpoints.** Auth endpoints (`/auth/...`,
 *    which carry passwords/OTP) and Data Room vault endpoints (`/data-room/...`,
 *    which carry credential/secret values, R16.7) are logged at
 *    [HttpLoggingInterceptor.Level.HEADERS] so their request/response **bodies**
 *    are omitted. All other endpoints are logged at
 *    [HttpLoggingInterceptor.Level.BODY] for debuggability.
 *
 * Logging is enabled only in debug builds; in release it is forced to
 * [HttpLoggingInterceptor.Level.NONE] so nothing is logged at all (defense in
 * depth alongside the redaction above, R23.2).
 */
@Singleton
class RedactingLoggingInterceptor @Inject constructor() : Interceptor {

    private val verboseLogger = buildLogger(
        if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BODY else HttpLoggingInterceptor.Level.NONE,
    )

    private val headersOnlyLogger = buildLogger(
        if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.HEADERS else HttpLoggingInterceptor.Level.NONE,
    )

    override fun intercept(chain: Interceptor.Chain): Response {
        val path = chain.request().url.encodedPath
        val delegate = if (isSensitivePath(path)) headersOnlyLogger else verboseLogger
        return delegate.intercept(chain)
    }

    private fun buildLogger(level: HttpLoggingInterceptor.Level): HttpLoggingInterceptor =
        HttpLoggingInterceptor().apply {
            setLevel(level)
            redactHeader("Cookie")
            redactHeader("Set-Cookie")
            redactHeader("Authorization")
        }

    /**
     * True for endpoints whose bodies may carry secrets: authentication
     * (passwords, OTP, reset tokens) and the Data Room vault (credential values).
     */
    private fun isSensitivePath(encodedPath: String): Boolean =
        encodedPath.contains(AUTH_PREFIX) || encodedPath.contains(DATA_ROOM_PREFIX)

    private companion object {
        const val AUTH_PREFIX = "/auth"
        const val DATA_ROOM_PREFIX = "/data-room"
    }
}
