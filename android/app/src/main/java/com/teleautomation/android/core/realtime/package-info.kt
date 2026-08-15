/**
 * `core.realtime` — pure, device-independent realtime (`/ws`) event modelling.
 *
 * Holds the sealed [com.teleautomation.android.core.realtime.RealtimeEvent]
 * hierarchy and the pure [com.teleautomation.android.core.realtime.RealtimeFrameRouter]
 * that parses a raw WebSocket text frame and routes it by its `type` field to a
 * typed event (R22.2, R22.3).
 *
 * Everything here lives in `core` with no Android/OkHttp/Retrofit dependency
 * (only `kotlinx.serialization.json`, a plain-JVM library) so the routing logic
 * is unit/property testable off-device. The OkHttp WebSocket client
 * (`RealtimeClient`, task 4.5) consumes this router; it never re-implements the
 * parsing itself.
 *
 * Backing property (Property 26): frame routing tolerates arbitrary frames —
 * a recognized `type` routes to its typed event, while an unrecognized `type`,
 * a non-object frame, or malformed/unparseable JSON maps to
 * [com.teleautomation.android.core.realtime.RealtimeEvent.Unknown] without
 * throwing.
 */
package com.teleautomation.android.core.realtime
