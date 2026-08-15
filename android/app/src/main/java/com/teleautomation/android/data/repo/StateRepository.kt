package com.teleautomation.android.data.repo

import com.teleautomation.android.core.ConnectivityChecker
import com.teleautomation.android.core.NetworkResult
import com.teleautomation.android.data.api.FleetActionResponse
import com.teleautomation.android.data.api.FleetState
import com.teleautomation.android.data.api.StateApiService
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for the fleet dashboard: fleet state retrieval and the start-all /
 * stop-all / reach-reset control actions (R6).
 *
 * Wraps [StateApiService] through [safeApiCall] so every method returns the uniform
 * [NetworkResult] with a retry closure capturing the original parameters
 * (R25, R26). No local or fabricated data is ever substituted for a Backend
 * response (R23.1): [fetchState] always reflects `GET /state`, and the figures the
 * dashboard renders (account/running/resting counts, posts, success rate, next-cycle
 * countdown) are pure properties derived on [FleetState] itself.
 *
 * The control actions are gated on the Backend by the fleet-admin dependency; an
 * HTTP 403 for a non-Admin Operator returns a [NetworkResult.Error] (kind
 * [com.teleautomation.android.core.ErrorKind.Client4xx], `httpStatus = 403`) so the
 * caller can show an authorization error and leave local state unchanged (R4.6).
 *
 * The DashboardViewModel (task 9.7) consumes these methods; this layer performs no
 * timeout, confirmation, or navigation policy. Reach reset must be gated behind an
 * explicit confirmation by the caller (R6.8, R6.9, see
 * [com.teleautomation.android.core.ConfirmationGate]) before [resetStats] is called.
 * Post-action running-state reflection is driven by the realtime `state` event and
 * dashboard refresh (R22.5), not by the action response bodies.
 */
@Singleton
class StateRepository @Inject constructor(
    private val stateApi: StateApiService,
    private val connectivity: ConnectivityChecker,
) {

    /**
     * Fetches fleet state from `GET /state` (R6.1).
     *
     * Used for the initial dashboard load, pull-to-refresh (R6.10), and the
     * post-reconnect refresh (R22.5). On failure the returned
     * [NetworkResult.Error] retains a retry that re-issues the same request, and the
     * caller retains the most recently displayed figures unchanged (R6.2).
     */
    suspend fun fetchState(): NetworkResult<FleetState> =
        safeApiCall(connectivity) { stateApi.getState() }

    /**
     * Calls `POST /start` to start all logged-in accounts (R6.4).
     *
     * The Backend queues the start asynchronously and returns immediately; the
     * resulting running state is reflected through the realtime `state` event /
     * refresh rather than this response.
     */
    suspend fun startAll(): NetworkResult<FleetActionResponse> =
        safeApiCall(connectivity) { stateApi.startAll() }

    /**
     * Calls `POST /stop` to stop all accounts (R6.5).
     */
    suspend fun stopAll(): NetworkResult<FleetActionResponse> =
        safeApiCall(connectivity) { stateApi.stopAll() }

    /**
     * Calls `POST /stats/reset` to reset reach/stat counters (R6.8).
     *
     * This is a destructive action: callers MUST invoke it only after an explicit
     * confirm outcome (R6.8, R6.9). On the cancel path the call is never made.
     */
    suspend fun resetStats(): NetworkResult<FleetActionResponse> =
        safeApiCall(connectivity) { stateApi.resetStats() }
}
