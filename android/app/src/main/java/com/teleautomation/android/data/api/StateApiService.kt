package com.teleautomation.android.data.api

import kotlinx.serialization.Serializable
import retrofit2.http.GET
import retrofit2.http.POST

/**
 * Retrofit interface for the fleet dashboard's Backend routes (R6).
 *
 * Maps 1:1 to the existing FastAPI endpoints in `server.py` (no new or mock
 * endpoints, R23.2):
 *  - `GET  /state`        — full fleet UI state (`build_ui_state`).
 *  - `POST /start`        — queue start for every logged-in account.
 *  - `POST /stop`         — stop all accounts.
 *  - `POST /stats/reset`  — reset daily stat counters / live tick display.
 *
 * The fleet-control routes (`/start`, `/stop`, `/stats/reset`) are gated on the
 * Backend by the fleet-admin dependency; a non-Admin Operator receives HTTP 403,
 * which `safeApiCall` surfaces as [com.teleautomation.android.core.ErrorKind.Client4xx]
 * for the authorization handling in R4.6. The session cookie is attached
 * automatically by the encrypted cookie jar (R23.3) and the request origin is
 * supplied per call by the dynamic base-URL interceptor.
 *
 * Created from the shared Retrofit instance via Hilt (`ApiModule`). Each function
 * is `suspend`; the `/start`, `/stop`, and `/stats/reset` calls send an empty body
 * (the Backend treats the reset payload as optional).
 */
interface StateApiService {

    /** `GET /state` — fleet state backing the dashboard figures (R6.1, R6.2). */
    @GET("state")
    suspend fun getState(): FleetState

    /** `POST /start` — start all logged-in accounts (R6.4). */
    @POST("start")
    suspend fun startAll(): FleetActionResponse

    /** `POST /stop` — stop all accounts (R6.5). */
    @POST("stop")
    suspend fun stopAll(): FleetActionResponse

    /** `POST /stats/reset` — reset reach/stat counters (R6.8). */
    @POST("stats/reset")
    suspend fun resetStats(): FleetActionResponse
}

/**
 * Lean response for the fleet-control actions `/start`, `/stop`, and `/stats/reset`.
 *
 * All three Backend handlers return a `status` token (e.g. `"queued"`, `"stopped"`,
 * `"ok"`, `"error"`) and `/start` additionally returns a human-readable `message`.
 * `/stop` and `/stats/reset` also splat the full UI state into their response; those
 * extra keys are ignored by the lenient JSON converter (R22.3) because the
 * authoritative post-action state is delivered via the realtime `state` event and
 * the dashboard refresh (R22.5), not parsed from the action response here.
 */
@Serializable
data class FleetActionResponse(
    /** Backend status token for the action (`queued` / `stopped` / `ok` / `error`). */
    val status: String? = null,

    /** Optional human-readable detail (populated by `/start`). */
    val message: String? = null,
)
