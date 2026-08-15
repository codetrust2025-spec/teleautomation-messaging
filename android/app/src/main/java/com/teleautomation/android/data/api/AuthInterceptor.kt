package com.teleautomation.android.data.api

import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Guarantees credential-inclusion semantics for every Backend request.
 *
 * The Backend authenticates via a session cookie (mirroring the Web_App's
 * `fetch(..., { credentials: 'include' })`). On Android the actual cookie
 * attachment is performed by [com.teleautomation.android.data.local.EncryptedCookieJar],
 * which is installed on the OkHttp client and replays the stored session
 * cookie(s) on every matching request (R23.3). Because that happens at the
 * client level, there is intentionally **no** additional header rewriting to do
 * here: duplicating the cookie jar's work would risk diverging from RFC 6265
 * domain/path matching and double-sending cookies.
 *
 * This interceptor is therefore a deliberate thin pass-through. It is included
 * because the design lists it explicitly as the single, named place that
 * documents and owns the "credentials are attached" contract, and so that any
 * future cross-cutting credential concern (e.g. a non-cookie auth header) has an
 * obvious, already-wired home rather than being scattered across services.
 *
 * It must run together with [UnauthorizedInterceptor] (which reacts to `401`s).
 * Both are wired into the OkHttp client in a later task (3.5).
 */
@Singleton
class AuthInterceptor @Inject constructor() : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        // Credentials (the session cookie) are attached by the EncryptedCookieJar
        // at the client level, so the request proceeds unmodified.
        return chain.proceed(chain.request())
    }
}
