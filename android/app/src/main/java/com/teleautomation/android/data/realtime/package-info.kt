/**
 * `data.realtime` — the I/O half of the realtime `/ws` stack.
 *
 * Holds [com.teleautomation.android.data.realtime.RealtimeClient], the OkHttp
 * WebSocket client that opens the `/ws` connection, pumps each incoming frame
 * through the pure [com.teleautomation.android.core.realtime.RealtimeFrameRouter],
 * and reconnects with the exponential backoff defined by
 * [com.teleautomation.android.core.ReconnectBackoffPolicy] (R22.1, R22.4).
 *
 * It exposes typed events (`SharedFlow<RealtimeEvent>`) and the connection
 * lifecycle (`StateFlow<ConnectionState>`) that drives the offline indicator
 * (R22.7). The socket reuses the shared OkHttp client (and its encrypted cookie
 * jar) so the stored session authenticates the connection (R23.3).
 *
 * Pure event modelling/parsing lives in `core.realtime`; this package never
 * re-implements it.
 */
package com.teleautomation.android.data.realtime
