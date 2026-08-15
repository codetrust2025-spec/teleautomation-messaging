package com.teleautomation.android.data.repo

import com.teleautomation.android.core.ConnectivityChecker
import com.teleautomation.android.core.NetworkResult
import com.teleautomation.android.data.api.AccountActionResponse
import com.teleautomation.android.data.api.AccountsApiService
import com.teleautomation.android.data.api.AccountsResponse
import com.teleautomation.android.data.api.DisplayNameRequest
import com.teleautomation.android.data.api.DisplayNameResponse
import com.teleautomation.android.data.api.PostingModeRequest
import com.teleautomation.android.data.api.PostingModeResponse
import com.teleautomation.android.data.api.ProvisionSlotResponse
import com.teleautomation.android.data.api.RefreshJoinedRequest
import com.teleautomation.android.data.api.RefreshJoinedResponse
import com.teleautomation.android.data.api.ShutdownClearResponse
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for account/fleet management: the slot roster, per-account start/stop,
 * display-name edit, posting-mode read/set, joined-count refresh, slot provisioning,
 * and shutdown-clear (R7).
 *
 * Wraps [AccountsApiService] through [safeApiCall] so every method returns the
 * uniform [NetworkResult] with a retry closure capturing the original parameters
 * (R25, R26). No local or fabricated data is ever substituted for a Backend
 * response (R23.1): each method reflects exactly what its endpoint returns, and the
 * caller updates the displayed account row from the response (status from
 * start/stop, name from display-name, mode from posting-mode, joined count from
 * refresh-joined) while leaving prior state unchanged on failure (R7.2, R7.4).
 *
 * The composite [com.teleautomation.android.data.api.AccountSlot] rows the screen
 * renders are assembled by the ViewModel (task 10.3) from [listAccounts] plus the
 * fleet `/state` worker map and per-slot posting mode — `/accounts` alone does not
 * carry display name, status, joined count, or posting mode (see [AccountsResponse]
 * KDoc).
 *
 * The fleet-control routes are gated on the Backend by the fleet-admin dependency;
 * an HTTP 403 for a non-Admin returns a [NetworkResult.Error] (kind
 * [com.teleautomation.android.core.ErrorKind.Client4xx], `httpStatus = 403`) so the
 * caller can show an authorization error and leave local state unchanged (R4.6).
 * Display-name length validation `[1,64]` (task 10.2) is applied by the caller
 * before [setDisplayName] so an invalid name is never transmitted (R7.6).
 */
@Singleton
class AccountsRepository @Inject constructor(
    private val accountsApi: AccountsApiService,
    private val connectivity: ConnectivityChecker,
) {

    /**
     * Fetches the configured slot roster from `GET /accounts` (R7.1).
     *
     * Returns the roster only; the ViewModel merges it with `/state` and per-slot
     * posting mode to build the displayed rows. On failure the caller retains any
     * previously displayed list unchanged (R7.2).
     */
    suspend fun listAccounts(): NetworkResult<AccountsResponse> =
        safeApiCall(connectivity) { accountsApi.listAccounts() }

    /**
     * Starts a specific account via `POST /account/{slot}/start` (R7.3).
     *
     * @param slot the target Account_Slot.
     * @param feature `""` (all), `"campaign"`, or `"forwarding"`.
     */
    suspend fun startAccount(slot: String, feature: String = ""): NetworkResult<AccountActionResponse> =
        safeApiCall(connectivity) { accountsApi.startAccount(slot, feature) }

    /**
     * Stops a specific account via `POST /account/{slot}/stop` (R7.3).
     *
     * @param slot the target Account_Slot.
     * @param feature `""` (all), `"campaign"`, or `"forwarding"`.
     */
    suspend fun stopAccount(slot: String, feature: String = ""): NetworkResult<AccountActionResponse> =
        safeApiCall(connectivity) { accountsApi.stopAccount(slot, feature) }

    /**
     * Sets an account's display name via `POST /account/{slot}/display-name` (R7.5).
     *
     * The caller MUST validate the name length `[1,64]` before invoking; this layer
     * does not re-validate (R7.6). On success the caller shows the returned
     * `account_info.display_name`.
     */
    suspend fun setDisplayName(slot: String, displayName: String): NetworkResult<DisplayNameResponse> =
        safeApiCall(connectivity) { accountsApi.setDisplayName(slot, DisplayNameRequest(displayName)) }

    /**
     * Reads an account's posting mode via `GET /account/{slot}/posting-mode` (R7.7).
     */
    suspend fun getPostingMode(slot: String): NetworkResult<PostingModeResponse> =
        safeApiCall(connectivity) { accountsApi.getPostingMode(slot) }

    /**
     * Sets an account's posting mode via `POST /account/{slot}/posting-mode` (R7.7).
     *
     * Only the changed fields are sent; the Backend requires at least one of `mode`,
     * `campaignEnabled`, `forwardingEnabled`, `forwardSourceType`, or
     * `forwardDispatch`. The caller sets the displayed mode from the response.
     */
    suspend fun setPostingMode(
        slot: String,
        mode: String? = null,
        campaignEnabled: Boolean? = null,
        forwardingEnabled: Boolean? = null,
        forwardSourceType: String? = null,
        forwardDispatch: String? = null,
    ): NetworkResult<PostingModeResponse> =
        safeApiCall(connectivity) {
            accountsApi.setPostingMode(
                slot,
                PostingModeRequest(
                    mode = mode,
                    campaignEnabled = campaignEnabled,
                    forwardingEnabled = forwardingEnabled,
                    forwardSourceType = forwardSourceType,
                    forwardDispatch = forwardDispatch,
                ),
            )
        }

    /**
     * Rescans joined-group counts for a slot via `POST /account/refresh-joined`
     * (R7.8). The slot is sent in the body. When the account is running the Backend
     * defers the scan and returns `queued = true`; the refreshed count then arrives
     * via the realtime `state` event.
     */
    suspend fun refreshJoined(slot: String): NetworkResult<RefreshJoinedResponse> =
        safeApiCall(connectivity) { accountsApi.refreshJoined(RefreshJoinedRequest(slot)) }

    /**
     * Provisions the next account slot via `POST /accounts/provision-slot` (R7.9).
     *
     * On a non-success status the caller adds no entry to the displayed list (R7.10).
     */
    suspend fun provisionSlot(): NetworkResult<ProvisionSlotResponse> =
        safeApiCall(connectivity) { accountsApi.provisionSlot() }

    /**
     * Clears a shutdown-list entry via `POST /account/{slot}/shutdown/clear` (R7.12).
     *
     * On a success status the caller removes the entry from the displayed shutdown
     * list.
     */
    suspend fun clearShutdown(slot: String): NetworkResult<ShutdownClearResponse> =
        safeApiCall(connectivity) { accountsApi.clearShutdown(slot) }
}
