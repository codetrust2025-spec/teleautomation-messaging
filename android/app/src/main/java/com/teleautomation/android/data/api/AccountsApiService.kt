package com.teleautomation.android.data.api

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit interface for the Backend account/fleet-management routes (R7).
 *
 * Maps 1:1 to the existing FastAPI endpoints in `server.py` (no new or mock
 * endpoints, R23.2):
 *  - `GET  /accounts`                         — slot roster ([AccountsResponse]).
 *  - `POST /account/{slot}/start`             — start one account (R7.3).
 *  - `POST /account/{slot}/stop`              — stop one account (R7.3).
 *  - `POST /account/{slot}/display-name`      — rename one account (R7.5).
 *  - `GET  /account/{slot}/posting-mode`      — read posting mode (R7.7).
 *  - `POST /account/{slot}/posting-mode`      — set posting mode (R7.7).
 *  - `POST /account/refresh-joined`           — rescan joined counts (R7.8).
 *  - `POST /accounts/provision-slot`          — add a new slot (R7.9).
 *  - `POST /account/{slot}/shutdown/clear`    — clear a shutdown entry (R7.12).
 *
 * Path-templated routes take the slot via [Path]; the per-account start/stop routes
 * also accept an optional `feature` [Query] (`campaign` / `forwarding`; empty means
 * all). Note `refresh-joined` is a *fleet-level* route (`/account/refresh-joined`,
 * confirmed against `server.py`) that takes the target slot in the request **body**
 * ([RefreshJoinedRequest]), not the path.
 *
 * The fleet-control routes (`start`, `stop`, `shutdown/clear`, `provision-slot`) are
 * gated on the Backend by the fleet-admin dependency; a non-Admin receives HTTP 403,
 * which `safeApiCall` surfaces as [com.teleautomation.android.core.ErrorKind.Client4xx]
 * for the authorization handling in R4.6. The session cookie is attached
 * automatically by the encrypted cookie jar (R23.3) and the request origin is
 * supplied per call by the dynamic base-URL interceptor.
 *
 * Created from the shared Retrofit instance via Hilt (`ApiModule`). Each function is
 * `suspend`; the repository layer wraps every call in `safeApiCall`.
 */
interface AccountsApiService {

    /** `GET /accounts` — configured slot roster (R7.1). */
    @GET("accounts")
    suspend fun listAccounts(): AccountsResponse

    /** `POST /account/{slot}/start` — start one account, optional feature (R7.3). */
    @POST("account/{slot}/start")
    suspend fun startAccount(
        @Path("slot") slot: String,
        @Query("feature") feature: String = "",
    ): AccountActionResponse

    /** `POST /account/{slot}/stop` — stop one account, optional feature (R7.3). */
    @POST("account/{slot}/stop")
    suspend fun stopAccount(
        @Path("slot") slot: String,
        @Query("feature") feature: String = "",
    ): AccountActionResponse

    /** `POST /account/{slot}/display-name` — set the dashboard label (R7.5). */
    @POST("account/{slot}/display-name")
    suspend fun setDisplayName(
        @Path("slot") slot: String,
        @Body request: DisplayNameRequest,
    ): DisplayNameResponse

    /** `GET /account/{slot}/posting-mode` — read the posting mode (R7.7). */
    @GET("account/{slot}/posting-mode")
    suspend fun getPostingMode(@Path("slot") slot: String): PostingModeResponse

    /** `POST /account/{slot}/posting-mode` — set the posting mode (R7.7). */
    @POST("account/{slot}/posting-mode")
    suspend fun setPostingMode(
        @Path("slot") slot: String,
        @Body request: PostingModeRequest,
    ): PostingModeResponse

    /** `POST /account/refresh-joined` — rescan joined counts for one slot (R7.8). */
    @POST("account/refresh-joined")
    suspend fun refreshJoined(@Body request: RefreshJoinedRequest): RefreshJoinedResponse

    /** `POST /accounts/provision-slot` — provision the next account slot (R7.9). */
    @POST("accounts/provision-slot")
    suspend fun provisionSlot(): ProvisionSlotResponse

    /** `POST /account/{slot}/shutdown/clear` — clear one shutdown entry (R7.12). */
    @POST("account/{slot}/shutdown/clear")
    suspend fun clearShutdown(@Path("slot") slot: String): ShutdownClearResponse
}
