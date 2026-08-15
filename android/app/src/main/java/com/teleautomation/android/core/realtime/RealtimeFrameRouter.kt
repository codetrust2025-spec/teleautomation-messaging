package com.teleautomation.android.core.realtime

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Pure, JVM-testable router that turns a raw `/ws` text frame into a typed
 * [RealtimeEvent] (R22.2, R22.3).
 *
 * The function is **total**: it never throws for any input. A frame is routed by
 * its top-level `type` field; an unrecognized `type`, a frame that is not a JSON
 * object, a missing/non-string `type`, or malformed/unparseable JSON all map to
 * [RealtimeEvent.Unknown]. This is the contract Property 26 exercises with
 * well-formed, unknown-type, and malformed generators.
 *
 * Parsing is intentionally lenient ([Json.isLenient] + [Json.ignoreUnknownKeys])
 * so the router tolerates Backend evolution and slightly off-spec payloads
 * without dropping the connection. It depends only on
 * `kotlinx.serialization.json`, keeping it free of any Android/OkHttp dependency.
 */
object RealtimeFrameRouter {

    /** Lenient JSON reader shared across calls; ignores unknown keys (R22.3). */
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    /** Backend `type` discriminator values this router recognizes. */
    private const val TYPE_STATE = "state"
    private const val TYPE_MEMBERSHIP = "membership"
    private const val TYPE_INBOX = "inbox"
    private const val TYPE_CRM = "crm"
    private const val TYPE_VOICE_CALL = "voice_call"
    private const val TYPE_INCOMING_CALL = "incoming_call"
    private const val TYPE_DAILY_STATS = "daily_stats"
    private const val TYPE_EVENT = "event"

    /**
     * Routes a single raw WebSocket text [rawFrame] to a [RealtimeEvent].
     *
     * Returns [RealtimeEvent.Unknown] (never throws) when the frame is not a JSON
     * object, has no string `type`, carries an unrecognized `type`, or cannot be
     * parsed at all.
     */
    fun route(rawFrame: String): RealtimeEvent {
        val frame = parseObjectOrNull(rawFrame) ?: return RealtimeEvent.Unknown
        val type = frame.stringOrNull("type") ?: return RealtimeEvent.Unknown

        return try {
            when (type) {
                TYPE_STATE -> RealtimeEvent.State(frame)
                TYPE_MEMBERSHIP -> RealtimeEvent.Membership(
                    slot = frame.stringOrNull("slot"),
                    payload = frame,
                )
                TYPE_INBOX -> RealtimeEvent.Inbox(
                    event = frame.stringOrNull("event"),
                    slot = frame.stringOrNull("slot"),
                    payload = frame,
                )
                TYPE_CRM -> RealtimeEvent.Crm(
                    event = frame.stringOrNull("event"),
                    slot = frame.stringOrNull("slot"),
                    payload = frame,
                )
                TYPE_VOICE_CALL -> RealtimeEvent.VoiceCall(
                    event = frame.stringOrNull("event"),
                    slot = frame.stringOrNull("slot"),
                    payload = frame,
                )
                TYPE_INCOMING_CALL -> RealtimeEvent.IncomingCall(
                    event = frame.stringOrNull("event"),
                    slot = frame.stringOrNull("slot"),
                    payload = frame,
                )
                TYPE_DAILY_STATS -> RealtimeEvent.DailyStats(
                    stats = frame["daily_stats"] ?: JsonNull,
                )
                TYPE_EVENT -> RealtimeEvent.Event(
                    name = frame.stringOrNull("event"),
                    data = frame,
                )
                else -> RealtimeEvent.Unknown
            }
        } catch (_: Throwable) {
            // Defensive: routing reads only already-parsed JSON, but the contract
            // is that no input can ever produce a thrown exception (R22.3).
            RealtimeEvent.Unknown
        }
    }

    /**
     * Leniently parses [raw] into a [JsonObject], or returns `null` if it is not
     * valid JSON or not a JSON object (e.g. an array, number, string, or `null`).
     */
    private fun parseObjectOrNull(raw: String): JsonObject? =
        try {
            json.parseToJsonElement(raw) as? JsonObject
        } catch (_: Throwable) {
            null
        }

    /**
     * Reads [key] from this object as a string, or `null` when the field is
     * absent or is not a JSON string primitive.
     */
    private fun JsonObject.stringOrNull(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
}
