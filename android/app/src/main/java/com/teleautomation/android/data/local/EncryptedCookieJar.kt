package com.teleautomation.android.data.local

import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import javax.inject.Inject
import javax.inject.Singleton

/**
 * OkHttp [CookieJar] backed by the encrypted [SessionStore].
 *
 * The Backend authenticates via a session cookie (mirroring the Web_App's
 * `fetch(..., { credentials: 'include' })`). This jar persists cookies received
 * on responses into the encrypted store and replays the matching cookie(s) on
 * every subsequent request, so the session is attached automatically (R23.3) and
 * is restored across app restarts (R2.1).
 */
@Singleton
class EncryptedCookieJar @Inject constructor(
    private val sessionStore: SessionStore,
) : CookieJar {

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        if (cookies.isEmpty()) return
        sessionStore.saveSession(cookies)
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val now = System.currentTimeMillis()
        return sessionStore.loadSession().filter { cookie ->
            cookie.expiresAt > now && cookie.matches(url)
        }
    }
}
