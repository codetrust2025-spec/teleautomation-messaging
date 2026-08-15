package com.teleautomation.android.data.repo

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import com.teleautomation.android.core.BackendUrlPolicy
import com.teleautomation.android.core.BackendUrlResult
import com.teleautomation.android.data.local.BackendConfig
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Owns the runtime-configurable Backend base URL (R23.6).
 *
 * Validation and WebSocket derivation are delegated to the pure
 * [BackendUrlPolicy] in `core`; this repository adds persistence (DataStore
 * Preferences) and the OkHttp-typed accessors the networking layer consumes.
 *
 * Only a syntactically valid URL using the `http`, `https`, `ws`, or `wss` scheme
 * with a non-empty host is accepted; any other value is rejected with an
 * [InvalidBackendConfigException] and is **not** persisted (R23.6, Property 28).
 */
@Singleton
class BackendConfigRepository @Inject constructor(
    private val dataStore: DataStore<Preferences>,
) {

    /**
     * Emits the current [BackendConfig], or `null` when no valid base URL has been
     * configured yet. A stored value that somehow fails validation is treated as
     * unset rather than surfaced as authoritative.
     */
    val config: Flow<BackendConfig?> = dataStore.data.map { prefs ->
        prefs[KEY_BASE_URL]
            ?.takeIf { BackendUrlPolicy.validate(it) is BackendUrlResult.Valid }
            ?.let { BackendConfig(baseUrl = it) }
    }

    /**
     * Validates [raw] and, when valid, persists it as the Backend base URL.
     *
     * @return [Result.success] with [Unit] when the value was accepted and stored;
     *   [Result.failure] wrapping an [InvalidBackendConfigException] (whose message
     *   identifies the invalid configuration) when rejected. Rejected values are
     *   never persisted (R23.6).
     */
    suspend fun setBaseUrl(raw: String): Result<Unit> =
        when (val result = BackendUrlPolicy.validate(raw)) {
            is BackendUrlResult.Valid -> {
                dataStore.edit { prefs -> prefs[KEY_BASE_URL] = result.canonical }
                Result.success(Unit)
            }

            is BackendUrlResult.Invalid ->
                Result.failure(InvalidBackendConfigException(result.reason))
        }

    /**
     * The current Backend base URL as an OkHttp [HttpUrl] for HTTP/Retrofit use, or
     * `null` when none is configured.
     *
     * Because OkHttp's [HttpUrl] models only `http`/`https`, a configured `ws`/`wss`
     * base is mapped to its `http`/`https` equivalent — the URL OkHttp actually
     * connects to. The WebSocket scheme distinction is preserved by
     * [currentWebSocketUrl] / [deriveWsUrl].
     */
    suspend fun currentBaseUrl(): HttpUrl? =
        config.first()?.baseUrl?.let { toBaseHttpUrl(it) }

    /**
     * The canonical WebSocket URL string (`ws`/`wss`) derived from the current base
     * URL, or `null` when none is configured. Maps `http→ws` and `https→wss`,
     * preserves host and port, and targets `/ws` (Property 28).
     */
    suspend fun currentWebSocketUrl(): String? =
        config.first()?.baseUrl?.let { BackendUrlPolicy.deriveWebSocketUrl(it) }

    /**
     * Derives the WebSocket connection [HttpUrl] from an http/https [base].
     *
     * OkHttp performs WebSocket requests against `http`/`https` [HttpUrl]s and
     * upgrades the connection (an `https` base yields a secure `wss` connection,
     * an `http` base a `ws` connection). This returns [base] with its path set to
     * `/ws`; see [currentWebSocketUrl] for the canonical `ws`/`wss` string form.
     */
    fun deriveWsUrl(base: HttpUrl): HttpUrl =
        base.newBuilder().encodedPath("/ws").build()

    /**
     * Maps a validated base URL string to an `http`/`https` [HttpUrl], translating
     * a `ws`/`wss` scheme to its `http`/`https` equivalent first.
     */
    private fun toBaseHttpUrl(baseUrl: String): HttpUrl? {
        val httpEquivalent = when {
            baseUrl.startsWith("ws://", ignoreCase = true) -> "http://" + baseUrl.substring(5)
            baseUrl.startsWith("wss://", ignoreCase = true) -> "https://" + baseUrl.substring(6)
            else -> baseUrl
        }
        return httpEquivalent.toHttpUrlOrNull()
    }

    private companion object {
        val KEY_BASE_URL = stringPreferencesKey("backend_base_url")
    }
}

/**
 * Raised when a candidate Backend base URL is rejected by validation (R23.6). The
 * [message] identifies the invalid configuration for surfacing to the Operator.
 */
class InvalidBackendConfigException(message: String) : IllegalArgumentException(message)
