package com.teleautomation.android.data.realtime

import com.teleautomation.android.core.ReconnectBackoffPolicy
import com.teleautomation.android.core.realtime.ConnectionState
import com.teleautomation.android.core.realtime.RealtimeEvent
import com.teleautomation.android.core.realtime.RealtimeFrameRouter
import com.teleautomation.android.data.repo.BackendConfigRepository
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.coroutineContext
import kotlin.coroutines.resume

/**
 * Realtime `/ws` client over an OkHttp [WebSocket] (R22.1, R22.4, R22.7).
 *
 * This is the I/O half of the realtime stack. The pure frame parsing lives in
 * [RealtimeFrameRouter] (in `core.realtime`); this client owns only the socket
 * lifecycle: opening the connection, pumping incoming text frames through the
 * router, and reconnecting with exponential backoff. It never re-implements the
 * parsing itself.
 *
 * Responsibilities:
 * - On [connect], open a WebSocket to the derived `ws`/`wss` `/ws` URL (sourced
 *   from [BackendConfigRepository]) so an authenticated Operator's stream comes
 *   up promptly after authentication (R22.1).
 * - Expose every parsed frame on [events] and the live socket lifecycle on
 *   [connectionState] for the offline indicator (R22.7).
 * - On close or failure, reconnect using [ReconnectBackoffPolicy.backoffDelay]
 *   with an attempt index that increments per failed attempt and resets to `0`
 *   on each successful open (R22.4).
 *
 * The same [OkHttpClient] used for HTTP is injected here, so the WebSocket shares
 * the client's cookie jar and the stored session cookie authenticates the socket
 * (R23.3). Re-fetching `/state` and inbox on (re)open and routing events into
 * module repositories are handled by later tasks (30.1 / 30.2); this client only
 * exposes [events] + [connectionState] and runs the reconnect loop.
 *
 * Thread-safety: [events] and [connectionState] are backed by coroutine flows
 * that tolerate updates from OkHttp's dispatcher threads. The reconnect loop runs
 * on a private [CoroutineScope]; [connect] / [disconnect] are idempotent.
 */
@Singleton
class RealtimeClient @Inject constructor(
    private val okHttpClient: OkHttpClient,
    private val backendConfigRepository: BackendConfigRepository,
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _events = MutableSharedFlow<RealtimeEvent>(
        replay = 0,
        extraBufferCapacity = EVENT_BUFFER_CAPACITY,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )

    /**
     * Typed events routed from each incoming `/ws` text frame (R22.2, R22.3).
     * Unrecognized or malformed frames surface as [RealtimeEvent.Unknown] and the
     * stream continues; downstream collectors decide what (if anything) to do
     * with them.
     */
    val events: SharedFlow<RealtimeEvent> = _events.asSharedFlow()

    private val _connectionState = MutableStateFlow(ConnectionState.Disconnected)

    /**
     * The live socket lifecycle state. Any value other than
     * [ConnectionState.Connected] means the realtime stream is not established and
     * drives the offline indicator (R22.7).
     */
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    @Volatile
    private var connectionJob: Job? = null

    @Volatile
    private var activeSocket: WebSocket? = null

    /**
     * Starts the realtime connection (and its reconnect loop) if not already
     * running. Safe to call repeatedly; subsequent calls while a loop is active
     * are no-ops. Intended to be invoked once authentication completes (R22.1).
     */
    @Synchronized
    fun connect() {
        if (connectionJob?.isActive == true) return
        connectionJob = scope.launch { runConnectionLoop() }
    }

    /**
     * Stops the realtime connection and reconnect loop, closing any open socket
     * and resetting the state to [ConnectionState.Disconnected]. Safe to call when
     * already stopped.
     */
    @Synchronized
    fun disconnect() {
        connectionJob?.cancel()
        connectionJob = null
        activeSocket?.close(NORMAL_CLOSURE_CODE, CLIENT_DISCONNECT_REASON)
        activeSocket = null
        _connectionState.value = ConnectionState.Disconnected
    }

    /**
     * The reconnect loop: open, run until the socket terminates, then wait out the
     * backoff and try again. The attempt index increments on every terminated
     * attempt and is reset to `0` by [awaitConnection] on a successful open, so
     * the delay after a healthy connection drops starts again at the 1s base
     * (R22.4).
     */
    private suspend fun runConnectionLoop() {
        var attempt = 0
        try {
            while (coroutineContext.isActive) {
                _connectionState.value = ConnectionState.Connecting

                val wsUrl = currentWsUrl()
                if (wsUrl == null) {
                    // No Backend URL configured yet: nothing to dial. Surface the
                    // offline state and wait out the same backoff before re-checking.
                    _connectionState.value = ConnectionState.Offline
                    delay(ReconnectBackoffPolicy.backoffDelay(attempt).inWholeMilliseconds)
                    attempt++
                    continue
                }

                // Suspends until the socket closes or fails; resets `attempt` to 0
                // on a successful open via the supplied callback.
                awaitConnection(wsUrl) { attempt = 0 }

                // Connection ended: not established any more (R22.7), then back off
                // before the next attempt (R22.4).
                _connectionState.value = ConnectionState.Disconnected
                delay(ReconnectBackoffPolicy.backoffDelay(attempt).inWholeMilliseconds)
                attempt++
            }
        } finally {
            activeSocket?.cancel()
            activeSocket = null
        }
    }

    /** The derived `ws`/`wss` `/ws` URL, or `null` when no base URL is configured. */
    private suspend fun currentWsUrl(): String? {
        val base = backendConfigRepository.currentBaseUrl() ?: return null
        return backendConfigRepository.deriveWsUrl(base).toString()
    }

    /**
     * Opens a single WebSocket to [wsUrl] and suspends until it closes or fails.
     *
     * Incoming text frames are routed through [RealtimeFrameRouter] and emitted on
     * [events]. [onOpen] is invoked on a successful handshake so the caller can
     * reset the backoff attempt counter (R22.4). The continuation resumes exactly
     * once — on `onClosed` or `onFailure` — after which the caller backs off and
     * reconnects.
     */
    private suspend fun awaitConnection(
        wsUrl: String,
        onOpen: () -> Unit,
    ): Unit = suspendCancellableCoroutine { continuation ->
        val request = Request.Builder().url(wsUrl).build()

        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                onOpen()
                _connectionState.value = ConnectionState.Connected
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                emitFrame(text)
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                emitFrame(bytes.utf8())
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                // Acknowledge the peer's close so the socket terminates cleanly.
                webSocket.close(NORMAL_CLOSURE_CODE, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                resumeOnce(continuation)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                resumeOnce(continuation)
            }
        }

        val webSocket = okHttpClient.newWebSocket(request, listener)
        activeSocket = webSocket

        continuation.invokeOnCancellation {
            // Loop cancelled (disconnect()/scope teardown): drop the socket without
            // a graceful handshake so we don't block.
            webSocket.cancel()
        }
    }

    /** Routes a raw frame and publishes the typed event (never throws). */
    private fun emitFrame(rawFrame: String) {
        _events.tryEmit(RealtimeFrameRouter.route(rawFrame))
    }

    private fun resumeOnce(continuation: CancellableContinuation<Unit>) {
        if (continuation.isActive) {
            continuation.resume(Unit)
        }
    }

    private companion object {
        /**
         * Normal-closure status code per RFC 6455 used when the client initiates or
         * acknowledges a close.
         */
        const val NORMAL_CLOSURE_CODE = 1000

        const val CLIENT_DISCONNECT_REASON = "client disconnect"

        /**
         * Bounded buffer for bursts of events; oldest are dropped under sustained
         * overflow so a slow collector can never stall the socket reader thread.
         */
        const val EVENT_BUFFER_CAPACITY = 64
    }
}
