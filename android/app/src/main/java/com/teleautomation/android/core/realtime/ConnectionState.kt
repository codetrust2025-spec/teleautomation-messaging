package com.teleautomation.android.core.realtime

/**
 * The lifecycle state of the realtime `/ws` connection, surfaced by
 * `RealtimeClient.connectionState` and consumed by the offline indicator (R22.7).
 *
 * This is a pure, device-independent model (no Android/OkHttp dependency) so it
 * can be referenced from both the data layer (the OkHttp WebSocket client) and
 * the UI layer (`OfflineBanner`) without coupling them.
 *
 * - [Connecting]   — an open/reopen attempt is in progress (initial connect or a
 *                    reconnect after a drop), no live socket yet.
 * - [Connected]    — the socket is open and frames are flowing.
 * - [Disconnected] — the socket closed or failed and the client is waiting out
 *                    the reconnect backoff before the next attempt (R22.4).
 * - [Offline]      — no Backend WebSocket URL is configured, so no attempt can be
 *                    made; the client waits out the backoff and re-checks.
 *
 * Any state other than [Connected] means the realtime stream is not established,
 * which is what drives the offline indicator (R22.7).
 */
enum class ConnectionState {
    Connecting,
    Connected,
    Disconnected,
    Offline,
    ;

    /** True only while the realtime stream is live (R22.7). */
    val isConnected: Boolean
        get() = this == Connected
}
