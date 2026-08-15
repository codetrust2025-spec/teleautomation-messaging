package com.teleautomation.android.core

import java.net.URI
import java.net.URISyntaxException

/**
 * Pure, device-independent validation and WebSocket-derivation logic for the
 * configurable Backend base URL (R23.6).
 *
 * This logic lives in `core` (no Android, OkHttp, or Retrofit dependencies) so it
 * is unit/property testable on the plain JVM. The `data.repo` layer delegates to
 * it for both validation and the canonical WebSocket URL; see
 * `BackendConfigRepository`.
 *
 * Backing requirement (R23.6): the Backend host is configurable at runtime, only a
 * syntactically valid URL using the `http`, `https`, `ws`, or `wss` scheme with a
 * non-empty host is accepted, and any other value is rejected with an error
 * identifying the invalid configuration.
 *
 * Backing property (Property 28): a configuration string is accepted iff it is a
 * syntactically valid URL whose scheme is one of `http`/`https`/`ws`/`wss` and
 * whose host is non-empty; rejected values are not persisted. For any accepted
 * base URL the derived WebSocket URL maps `http→ws`/`https→wss` (and keeps
 * `ws`/`wss`), preserves host and port, and targets the `/ws` path.
 */
object BackendUrlPolicy {

    /** The only schemes accepted for a configured Backend base URL (R23.6). */
    val ALLOWED_SCHEMES: Set<String> = setOf("http", "https", "ws", "wss")

    /**
     * Validates a candidate Backend base URL [raw] without any side effects.
     *
     * Returns [BackendUrlResult.Valid] carrying the trimmed, canonical form when
     * [raw] is a syntactically valid URL whose (case-insensitive) scheme is in
     * [ALLOWED_SCHEMES] and whose host is non-empty. Otherwise returns
     * [BackendUrlResult.Invalid] with a human-readable reason describing the
     * problem. Adversarial values such as `javascript:...`, `file:...`, a blank
     * string, or a URL with an empty host are rejected here.
     */
    fun validate(raw: String): BackendUrlResult {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) {
            return BackendUrlResult.Invalid("Backend URL must not be blank.")
        }

        val uri = try {
            URI(trimmed)
        } catch (e: URISyntaxException) {
            return BackendUrlResult.Invalid(
                "Not a syntactically valid URL: ${e.reason ?: "malformed"}.",
            )
        }

        val scheme = uri.scheme?.lowercase()
            ?: return BackendUrlResult.Invalid(
                "Backend URL must include a scheme (one of ${allowedSchemesText()}).",
            )

        if (scheme !in ALLOWED_SCHEMES) {
            return BackendUrlResult.Invalid(
                "Unsupported URL scheme \"$scheme\"; expected one of ${allowedSchemesText()}.",
            )
        }

        val host = uri.host
        if (host.isNullOrEmpty()) {
            return BackendUrlResult.Invalid("Backend URL must include a non-empty host.")
        }

        return BackendUrlResult.Valid(trimmed)
    }

    /**
     * Derives the canonical WebSocket URL string for an already-accepted base URL
     * [baseUrl]. The scheme is mapped `http→ws` and `https→wss` (an already-`ws`
     * or `wss` base is preserved), the host and explicit port are preserved, and
     * the path is set to `/ws` — mirroring the Backend's root `/ws` endpoint.
     *
     * @throws IllegalArgumentException if [baseUrl] is not a URL using an allowed
     *   scheme with a non-empty host. Callers should pass only values that have
     *   already passed [validate].
     */
    fun deriveWebSocketUrl(baseUrl: String): String {
        val trimmed = baseUrl.trim()
        val uri = try {
            URI(trimmed)
        } catch (e: URISyntaxException) {
            throw IllegalArgumentException("Cannot derive WebSocket URL from invalid base URL.", e)
        }

        val wsScheme = when (uri.scheme?.lowercase()) {
            "http", "ws" -> "ws"
            "https", "wss" -> "wss"
            else -> throw IllegalArgumentException(
                "Cannot derive WebSocket URL: base scheme must be one of ${allowedSchemesText()}.",
            )
        }

        val host = uri.host
        require(!host.isNullOrEmpty()) {
            "Cannot derive WebSocket URL: base URL has no host."
        }

        val portPart = if (uri.port != -1) ":${uri.port}" else ""
        return "$wsScheme://$host$portPart/ws"
    }

    private fun allowedSchemesText(): String = ALLOWED_SCHEMES.joinToString("/")
}

/** Outcome of validating a candidate Backend base URL via [BackendUrlPolicy.validate]. */
sealed interface BackendUrlResult {
    /** The input is accepted; [canonical] is the trimmed value safe to persist. */
    data class Valid(val canonical: String) : BackendUrlResult

    /** The input is rejected; [reason] describes the invalid configuration (R23.6). */
    data class Invalid(val reason: String) : BackendUrlResult
}
