package com.teleautomation.android.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.teleautomation.android.data.api.Role
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.Cookie
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Encrypted, on-device store for the authenticated [Session] state.
 *
 * Persists the session cookie(s) returned by the Backend plus the authenticated
 * identity (username, [Role], handler reference) in [EncryptedSharedPreferences],
 * which encrypts both keys and values at rest using an AES-256 master key held in
 * the Android Keystore. This is the durable backing for the OkHttp
 * [EncryptedCookieJar] so the session cookie is attached to every authenticated
 * request (R23.3) and survives process death / app restarts (R2.1).
 *
 * Security: only the opaque session cookie is stored. No password is ever
 * persisted, and no plaintext secret is written outside the encrypted store.
 */
@Singleton
class SessionStore @Inject constructor(
    @ApplicationContext context: Context,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    private val prefs: SharedPreferences by lazy { createEncryptedPrefs(context) }

    private val lock = Any()

    // ── Session cookies ──────────────────────────────────────────────────────

    /**
     * Persists the supplied [cookies] as the current session, merging them with
     * any already-stored cookies. Cookies are keyed by (name, domain, path); a
     * newer cookie with the same key replaces the older one. Already-expired
     * cookies are dropped rather than written.
     */
    fun saveSession(cookies: List<Cookie>) {
        if (cookies.isEmpty()) return
        synchronized(lock) {
            val now = System.currentTimeMillis()
            val merged = LinkedHashMap<String, PersistedCookie>()
            for (existing in readCookies()) {
                merged[existing.identityKey()] = existing
            }
            for (cookie in cookies) {
                val persisted = PersistedCookie.from(cookie)
                if (persisted.expiresAt <= now) {
                    // An expired/cleared cookie removes any prior value.
                    merged.remove(persisted.identityKey())
                } else {
                    merged[persisted.identityKey()] = persisted
                }
            }
            writeCookies(merged.values.toList())
        }
    }

    /**
     * Returns the currently stored, non-expired session cookies as OkHttp
     * [Cookie] instances. Expired cookies are filtered out (and pruned).
     */
    fun loadSession(): List<Cookie> {
        synchronized(lock) {
            val now = System.currentTimeMillis()
            val stored = readCookies()
            val live = stored.filter { it.expiresAt > now }
            if (live.size != stored.size) {
                writeCookies(live)
            }
            return live.mapNotNull { it.toCookie() }
        }
    }

    /** True when at least one non-expired session cookie is stored. */
    fun hasSession(): Boolean {
        synchronized(lock) {
            val now = System.currentTimeMillis()
            return readCookies().any { it.expiresAt > now }
        }
    }

    /**
     * Clears all stored session state: cookies and identity. Invoked on logout
     * and on any unauthenticated (401) signal (R2.6).
     */
    fun clear() {
        synchronized(lock) {
            prefs.edit().clear().apply()
        }
    }

    // ── Identity ─────────────────────────────────────────────────────────────

    /**
     * Persists the authenticated identity reported by the Backend
     * `/auth/status` (or `/auth/login`) response.
     */
    fun saveIdentity(username: String?, role: Role, reference: String?) {
        synchronized(lock) {
            prefs.edit()
                .putString(KEY_USERNAME, username)
                .putString(KEY_ROLE, role.name)
                .putString(KEY_REFERENCE, reference)
                .apply()
        }
    }

    /** The stored Operator username, or null when none is stored. */
    fun username(): String? = synchronized(lock) { prefs.getString(KEY_USERNAME, null) }

    /**
     * The stored Operator [Role]. Defaults to [Role.ADMIN] when no role has been
     * stored or the stored value is unrecognized, matching the Web_App default.
     */
    fun role(): Role = synchronized(lock) {
        val stored = prefs.getString(KEY_ROLE, null) ?: return Role.ADMIN
        runCatching { Role.valueOf(stored) }.getOrDefault(Role.ADMIN)
    }

    /** The stored handler reference id, or null when none is stored. */
    fun reference(): String? = synchronized(lock) { prefs.getString(KEY_REFERENCE, null) }

    // ── Internal persistence helpers ───────────────────────────────────────────

    private fun readCookies(): List<PersistedCookie> {
        val raw = prefs.getString(KEY_COOKIES, null) ?: return emptyList()
        return runCatching {
            json.decodeFromString<List<PersistedCookie>>(raw)
        }.getOrDefault(emptyList())
    }

    private fun writeCookies(cookies: List<PersistedCookie>) {
        if (cookies.isEmpty()) {
            prefs.edit().remove(KEY_COOKIES).apply()
        } else {
            prefs.edit().putString(KEY_COOKIES, json.encodeToString(cookies)).apply()
        }
    }

    private fun createEncryptedPrefs(context: Context): SharedPreferences {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context,
            PREFS_FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    private companion object {
        const val PREFS_FILE_NAME = "teleautomation_session"
        const val KEY_COOKIES = "session_cookies"
        const val KEY_USERNAME = "identity_username"
        const val KEY_ROLE = "identity_role"
        const val KEY_REFERENCE = "identity_reference"
    }
}

/**
 * Serializable snapshot of an OkHttp [Cookie] for encrypted persistence.
 *
 * Captures the fields required to faithfully reconstruct the cookie and to
 * perform domain/path matching when attaching it to outgoing requests.
 */
@Serializable
internal data class PersistedCookie(
    val name: String,
    val value: String,
    val expiresAt: Long,
    val domain: String,
    val path: String,
    val secure: Boolean,
    val httpOnly: Boolean,
    val hostOnly: Boolean,
) {
    /** Stable identity used to de-duplicate cookies (matches RFC 6265 semantics). */
    fun identityKey(): String = "$name\u0000$domain\u0000$path"

    /** Reconstructs an OkHttp [Cookie]; returns null if the data is no longer valid. */
    fun toCookie(): Cookie? {
        val builder = Cookie.Builder()
            .name(name)
            .value(value)
            .path(path)
            .expiresAt(expiresAt)
        // hostOnly cookies use hostOnlyDomain (no leading-dot subdomain match);
        // otherwise the domain matches subdomains.
        if (hostOnly) {
            builder.hostOnlyDomain(domain)
        } else {
            builder.domain(domain)
        }
        if (secure) builder.secure()
        if (httpOnly) builder.httpOnly()
        return runCatching { builder.build() }.getOrNull()
    }

    companion object {
        fun from(cookie: Cookie): PersistedCookie = PersistedCookie(
            name = cookie.name,
            value = cookie.value,
            expiresAt = cookie.expiresAt,
            domain = cookie.domain,
            path = cookie.path,
            secure = cookie.secure,
            httpOnly = cookie.httpOnly,
            hostOnly = cookie.hostOnly,
        )
    }
}
