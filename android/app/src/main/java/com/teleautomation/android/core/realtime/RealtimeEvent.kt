package com.teleautomation.android.core.realtime

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/**
 * A single, parsed message pushed by the Backend over the `/ws` WebSocket.
 *
 * The Backend discriminates every frame by a top-level `type` field and spreads
 * the rest of the payload alongside it (see `server.py` / `services/*`):
 * `state`, `membership`, `inbox`, `crm`, `voice_call`, `incoming_call`,
 * `daily_stats`, and `event`. [RealtimeFrameRouter] maps each recognized `type`
 * to one of the variants below; anything it cannot recognize or parse becomes
 * [Unknown] (R22.2, R22.3).
 *
 * Payloads are kept as raw [JsonObject] / [JsonElement] here **on purpose**: the
 * per-module DTOs (e.g. `FleetState`, `InboxDelta`, `CrmDelta`, `CallSession`,
 * `DailyStats`) are introduced and refined by later tasks. Holding the lenient
 * JSON tree lets the routing logic stay total (it never has to reject a frame
 * because a nested field is missing or unexpected) while still surfacing the
 * common discriminator fields (`slot`, `event`) that downstream consumers route
 * on. Later tasks decode these payloads into typed models.
 */
sealed interface RealtimeEvent {

    /**
     * Fleet/dashboard state snapshot (`{"type":"state", ...state...}`).
     *
     * The Backend spreads the full UI state alongside `type`, so [payload] is the
     * entire frame object; a later task decodes it into `FleetState` (R6, R22.5).
     */
    data class State(val payload: JsonObject) : RealtimeEvent

    /**
     * Per-account group-membership update
     * (`{"type":"membership","slot":...,"joined_groups":...}`).
     */
    data class Membership(val slot: String?, val payload: JsonObject) : RealtimeEvent

    /**
     * Inbox delta (`{"type":"inbox","event":...,"slot":...,...}`) — e.g. a new
     * message, a sent reply, or a call event affecting a conversation (R11).
     */
    data class Inbox(
        val event: String?,
        val slot: String?,
        val payload: JsonObject,
    ) : RealtimeEvent

    /**
     * CRM/lead delta (`{"type":"crm","event":...,"slot":...,...}`) such as a lead
     * update or deletion, or a full CRM payload refresh (R13).
     */
    data class Crm(
        val event: String?,
        val slot: String?,
        val payload: JsonObject,
    ) : RealtimeEvent

    /**
     * Outgoing/voice-call lifecycle signal
     * (`{"type":"voice_call","event":...,"slot":...,"session":...}`) driving the
     * `dialing→ringing→active→ended/failed/missed` state machine (R12).
     */
    data class VoiceCall(
        val event: String?,
        val slot: String?,
        val payload: JsonObject,
    ) : RealtimeEvent

    /**
     * Incoming-call signal (`{"type":"incoming_call","event":...,"slot":...}`)
     * used to surface the ringing screen (R12.1).
     */
    data class IncomingCall(
        val event: String?,
        val slot: String?,
        val payload: JsonObject,
    ) : RealtimeEvent

    /**
     * Daily-statistics push (`{"type":"daily_stats","daily_stats":{...}}`). The
     * inner `daily_stats` value is exposed as [stats]; it is
     * [kotlinx.serialization.json.JsonNull] when the field is absent (R20.7).
     */
    data class DailyStats(val stats: JsonElement) : RealtimeEvent

    /**
     * Generic application event (`{"type":"event","event":<name>,...}`) such as
     * `STATS_RESET` or activity-log entries (R19); [name] is the inner `event`
     * value and [data] is the full frame object.
     */
    data class Event(val name: String?, val data: JsonObject) : RealtimeEvent

    /**
     * A frame that could not be recognized or parsed: an unknown/absent `type`, a
     * non-object frame, or malformed JSON. Consumers discard it and keep the
     * stream alive (R22.3).
     */
    data object Unknown : RealtimeEvent
}
