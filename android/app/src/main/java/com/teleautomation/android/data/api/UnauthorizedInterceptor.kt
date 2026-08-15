package com.teleautomation.android.data.api

import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Detects unauthenticated Backend responses and raises a global signal so the
 * app can clear its session and route back to Login.
 *
 * This mirrors the Web_App's global fetch interceptor, which dispatches an
 * `auth:required` event on any non-login / non-auth-status `401`
 * (`AuthContext.jsx`). On HTTP `401 Unauthorized` for any request whose path is
 * NOT [LOGIN_PATH] and NOT [STATUS_PATH], it emits [AuthEvents.unauthorized]
 * (R2.6, R26.4).
 *
 * Login and auth-status `401`s are deliberately excluded: a `401` there is the
 * *expected* "bad credentials" / "not signed in" answer to an explicit check,
 * not a session that expired mid-use, so reacting to them would wrongly force a
 * logout/redirect loop during normal sign-in.
 *
 * The interceptor never alters the response; it only observes the status code
 * and passes the original [Response] through unchanged.
 *
 * Wired into the OkHttp client in a later task (3.5).
 */
@Singleton
class UnauthorizedInterceptor @Inject constructor(
    private val authEvents: AuthEvents,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val response = chain.proceed(request)

        if (response.code == HTTP_UNAUTHORIZED && !isAuthExemptPath(request.url.encodedPath)) {
            authEvents.notifyUnauthorized()
        }

        return response
    }

    /**
     * True when the request targets the login or auth-status endpoint, for which
     * a `401` is an expected answer rather than a session-expiry signal.
     *
     * Matching is suffix-based on the normalized path so it holds whether the
     * configured base URL is the host root (`/auth/login`) or includes a path
     * prefix; a single trailing slash is tolerated.
     */
    private fun isAuthExemptPath(encodedPath: String): Boolean {
        val normalized = encodedPath.trimEnd('/')
        return normalized.endsWith(LOGIN_PATH) || normalized.endsWith(STATUS_PATH)
    }

    private companion object {
        const val HTTP_UNAUTHORIZED = 401
        const val LOGIN_PATH = "/auth/login"
        const val STATUS_PATH = "/auth/status"
    }
}
