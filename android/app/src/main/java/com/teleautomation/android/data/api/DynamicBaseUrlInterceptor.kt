package com.teleautomation.android.data.api

import com.teleautomation.android.data.repo.BackendConfigRepository
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Retargets every outgoing request at the currently-configured Backend base URL
 * (R23.6).
 *
 * The Backend host is **runtime-configurable** and may change while the app is
 * running ([BackendConfigRepository]). Retrofit, however, is built once with a
 * fixed placeholder base URL. Rather than rebuilding Retrofit (and every cached
 * `ApiService`) whenever the host changes, a single long-lived Retrofit/OkHttp
 * stack is kept and this interceptor rewrites each request's `scheme`, `host`,
 * and `port` to the current configuration just before it goes out. The original
 * relative path and query — which is what `ApiService` methods declare — are
 * preserved, so services resolve correctly against whatever host is configured at
 * call time.
 *
 * The configured base is a root origin (`scheme://host:port`), mirroring the
 * Web_App's `config.js`, which derives the API origin from `window.location`. The
 * Backend mounts its routes at the root, so only the origin is swapped; any path
 * prefix on the base URL is intentionally not merged.
 *
 * When no base URL has been configured yet, the request proceeds unchanged
 * against the placeholder host and fails as an ordinary connectivity error, which
 * `safeApiCall` classifies like any other (no fabricated success, R23.4).
 *
 * The lookup is a fast in-memory DataStore read; running it with [runBlocking] is
 * safe here because OkHttp invokes application interceptors on its own background
 * dispatcher threads, never the main thread.
 */
@Singleton
class DynamicBaseUrlInterceptor @Inject constructor(
    private val backendConfigRepository: BackendConfigRepository,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val base = runBlocking { backendConfigRepository.currentBaseUrl() }
            ?: return chain.proceed(request)

        val retargetedUrl = request.url.newBuilder()
            .scheme(base.scheme)
            .host(base.host)
            .port(base.port)
            .build()

        return chain.proceed(
            request.newBuilder().url(retargetedUrl).build(),
        )
    }
}
