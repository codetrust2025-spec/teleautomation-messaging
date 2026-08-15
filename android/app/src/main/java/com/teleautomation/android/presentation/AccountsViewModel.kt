package com.teleautomation.android.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.teleautomation.android.core.BoundedLengthResult
import com.teleautomation.android.core.DisplayNameValidator
import com.teleautomation.android.core.NetworkErrorClassifier
import com.teleautomation.android.core.NetworkResult
import com.teleautomation.android.core.ViewState
import com.teleautomation.android.core.ViewStateSelector
import com.teleautomation.android.data.api.AccountSlot
import com.teleautomation.android.data.api.PostingMode
import com.teleautomation.android.data.api.ShutdownEntry
import com.teleautomation.android.data.repo.AccountsRepository
import com.teleautomation.android.data.repo.StateRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Immutable UI state for the Accounts module — the list of composite account rows,
 * the shutdown list, and the transient per-account / provisioning indications (R7).
 *
 * @property accounts the transient state of the composite [AccountSlot] rows
 *   assembled from `GET /accounts` merged with the `GET /state` worker map (R7.1).
 *   On a load failure the last displayed rows are retained behind the error
 *   indication (R7.2, R25.4).
 * @property shutdownEntries the auto-shutdown entries read from
 *   [com.teleautomation.android.data.api.FleetState.shutdownList] (R7.11); cleared
 *   per slot via [clearShutdown] (R7.12).
 * @property busySlots slots with a per-account action (start/stop/rename/mode/
 *   refresh) in flight, used to disable controls and avoid duplicate submissions.
 * @property slotErrors per-slot error indications identifying the affected
 *   Account_Slot when one of its actions fails; the row's displayed values are left
 *   unchanged (R7.4, R7.6).
 * @property isProvisioning whether a provision-slot call is in flight (R7.9).
 * @property provisionError a transient error for a failed provisioning attempt; no
 *   row is added on failure (R7.10).
 * @property actionError a transient error for a failed shutdown-clear action (R7.12).
 * @property successMessage a confirmation message for a completed action, or `null`.
 */
data class AccountsUiState(
    val accounts: ViewState<List<AccountSlot>> = ViewState.Loading,
    val shutdownEntries: List<ShutdownEntry> = emptyList(),
    val busySlots: Set<String> = emptySet(),
    val slotErrors: Map<String, String> = emptyMap(),
    val isProvisioning: Boolean = false,
    val provisionError: String? = null,
    val actionError: String? = null,
    val successMessage: String? = null,
)

/**
 * Presentation-layer ViewModel for the Accounts module (R7.1–R7.12), shared by the
 * [com.teleautomation.android.ui.accounts.AccountsListScreen] and the
 * [com.teleautomation.android.ui.accounts.AccountDetailScreen].
 *
 * Responsibilities:
 *  - **Composite roster (R7.1, R7.2).** Loads `GET /accounts` and `GET /state`
 *    through [AccountsRepository]/[StateRepository] and assembles one
 *    [AccountSlot] per slot via [AccountSlot.from], merging the roster with each
 *    slot's worker state (status, posting mode). The shutdown list is taken from the
 *    same `/state` payload (R7.11). On failure the last rows are retained behind the
 *    error and a retry is offered (R7.2, R25.5).
 *  - **Per-account start/stop (R7.3, R7.4).** Reflects the displayed status from the
 *    Backend response token on success; on failure surfaces a slot-scoped error and
 *    leaves the displayed status unchanged.
 *  - **Display-name edit (R7.5, R7.6).** Validates the new name against `[1,64]` via
 *    [DisplayNameValidator] *before* calling the Backend; rejects invalid names
 *    without a network call and reflects the returned name on success.
 *  - **Posting-mode change (R7.7).** Submits the new mode and reflects the mode
 *    returned by the Backend.
 *  - **Refresh-joined (R7.8).** Updates the displayed joined-group count from the
 *    Backend response (or leaves it for the realtime `state` event when the scan was
 *    queued).
 *  - **Provision slot (R7.9, R7.10).** Adds the returned slot to the displayed list
 *    on success; adds nothing on failure.
 *  - **Shutdown clear (R7.11, R7.12).** Removes the entry from the displayed
 *    shutdown list on a successful clear.
 *
 * The fleet-control routes are gated on the Backend by the fleet-admin dependency; a
 * non-Admin Operator receives HTTP 403, surfaced here as an authorization error with
 * local state left unchanged (R4.6). The ViewModel performs no navigation and
 * touches no Android/Compose types so it stays unit-testable.
 */
@HiltViewModel
class AccountsViewModel @Inject constructor(
    private val accountsRepository: AccountsRepository,
    private val stateRepository: StateRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(AccountsUiState())
    val uiState: StateFlow<AccountsUiState> = _uiState.asStateFlow()

    /** Last successfully assembled rows, retained to apply per-account updates and to keep rows visible behind a load error (R7.2). */
    private var currentAccounts: List<AccountSlot> = emptyList()

    init {
        load(initial = true)
    }

    /** Re-issues the roster load after a failure (R7.2, R25.5). */
    fun retry() = load(initial = true)

    /** Re-loads the roster (e.g. pull-to-refresh), keeping any displayed rows. */
    fun refresh() = load(initial = false)

    /**
     * Fetches `GET /accounts` + `GET /state` and assembles the composite rows
     * ([AccountSlot.from]) plus the shutdown list (R7.1, R7.11). [initial] shows the
     * full-screen loading state on first load; a refresh keeps the current rows.
     */
    private fun load(initial: Boolean) {
        if (initial) _uiState.update { it.copy(accounts = ViewState.Loading) }
        viewModelScope.launch {
            val result = fetchRows()
            when (result) {
                is NetworkResult.Success -> currentAccounts = result.data
                NetworkResult.Empty -> currentAccounts = emptyList()
                else -> Unit
            }
            _uiState.update {
                it.copy(
                    accounts = ViewStateSelector.select(
                        result,
                        previousContent = currentAccounts.takeIf { rows -> rows.isNotEmpty() },
                    ),
                )
            }
        }
    }

    /**
     * Assembles the composite [AccountSlot] rows from the roster and the `/state`
     * worker map (R7.1), folding an empty roster to [NetworkResult.Empty] and an
     * accounts failure to a typed [NetworkResult.Error] whose retry re-runs the whole
     * assembly (R26.5). The shutdown list is updated as a side effect whenever
     * `/state` succeeds (R7.11), independent of the accounts outcome.
     */
    private suspend fun fetchRows(): NetworkResult<List<AccountSlot>> {
        val accountsResult = accountsRepository.listAccounts()
        val stateResult = stateRepository.fetchState()
        val fleet = (stateResult as? NetworkResult.Success)?.data
        if (fleet != null) {
            _uiState.update { it.copy(shutdownEntries = fleet.shutdownList.values.toList()) }
        }

        return when (accountsResult) {
            is NetworkResult.Success -> {
                val roster = accountsResult.data
                val rows = roster.accountSlots.map { slot ->
                    val workerState = fleet?.accountStates?.get(slot)
                    AccountSlot.from(
                        slot = slot,
                        info = null,
                        workerState = workerState,
                        postingMode = workerState?.postingMode ?: PostingMode.CAMPAIGN,
                        subscription = slot in roster.subscriptionSlots,
                    )
                }
                if (rows.isEmpty()) NetworkResult.Empty else NetworkResult.Success(rows)
            }

            is NetworkResult.Error -> NetworkResult.Error(
                kind = accountsResult.kind,
                message = accountsResult.message,
                retry = { fetchRows() },
                httpStatus = accountsResult.httpStatus,
            )

            NetworkResult.Empty -> NetworkResult.Empty
            NetworkResult.Loading -> NetworkResult.Loading
        }
    }

    /**
     * Starts one account via `POST /account/{slot}/start` and sets the displayed
     * status to the response token (R7.3); on failure surfaces a slot-scoped error
     * and leaves the status unchanged (R7.4).
     */
    fun startAccount(slot: String) = runSlotAction(slot) {
        when (val result = accountsRepository.startAccount(slot)) {
            is NetworkResult.Success -> reflectActionStatus(slot, result.data.status, result.data.message, "start")
            is NetworkResult.Error -> SlotResult.Fail(authMessage(result, "Could not start $slot."))
            else -> SlotResult.Fail("Could not start $slot.")
        }
    }

    /**
     * Stops one account via `POST /account/{slot}/stop` and sets the displayed
     * status to the response token (R7.3); on failure surfaces a slot-scoped error
     * and leaves the status unchanged (R7.4).
     */
    fun stopAccount(slot: String) = runSlotAction(slot) {
        when (val result = accountsRepository.stopAccount(slot)) {
            is NetworkResult.Success -> reflectActionStatus(slot, result.data.status, result.data.message, "stop")
            is NetworkResult.Error -> SlotResult.Fail(authMessage(result, "Could not stop $slot."))
            else -> SlotResult.Fail("Could not stop $slot.")
        }
    }

    /**
     * Edits a slot's display name (R7.5, R7.6). Validates `[1,64]` via
     * [DisplayNameValidator] before any network call; a rejected name surfaces a
     * slot-scoped error and the Backend is never called. On success the displayed
     * name reflects the name returned by the Backend.
     */
    fun editDisplayName(slot: String, name: String) {
        when (val validation = DisplayNameValidator.validate(name)) {
            is BoundedLengthResult.Rejected -> _uiState.update {
                it.copy(slotErrors = it.slotErrors + (slot to validation.reason))
            }

            BoundedLengthResult.Accepted -> runSlotAction(slot) {
                val trimmed = name.trim()
                when (val result = accountsRepository.setDisplayName(slot, trimmed)) {
                    is NetworkResult.Success -> {
                        if (result.data.success) {
                            val newName = result.data.accountInfo?.displayName
                                ?.takeIf { it.isNotBlank() } ?: trimmed
                            updateAccount(slot) { it.copy(displayName = newName) }
                            SlotResult.Ok("Renamed $slot.")
                        } else {
                            SlotResult.Fail(result.data.error ?: "Could not rename $slot.")
                        }
                    }

                    is NetworkResult.Error -> SlotResult.Fail(authMessage(result, "Could not rename $slot."))
                    else -> SlotResult.Fail("Could not rename $slot.")
                }
            }
        }
    }

    /**
     * Changes a slot's posting mode via `POST /account/{slot}/posting-mode` and sets
     * the displayed mode to the mode returned by the Backend (R7.7).
     */
    fun changePostingMode(slot: String, mode: PostingMode) = runSlotAction(slot) {
        val token = if (mode == PostingMode.FORWARDING) "forwarding" else "campaign"
        when (val result = accountsRepository.setPostingMode(slot, mode = token)) {
            is NetworkResult.Success -> {
                if (result.data.status.equals("error", ignoreCase = true)) {
                    SlotResult.Fail(result.data.message ?: "Could not change mode for $slot.")
                } else {
                    val resolved = result.data.postingMode
                    updateAccount(slot) { it.copy(postingMode = resolved) }
                    SlotResult.Ok("$slot set to ${resolved.name.lowercase()} mode.")
                }
            }

            is NetworkResult.Error -> SlotResult.Fail(authMessage(result, "Could not change mode for $slot."))
            else -> SlotResult.Fail("Could not change mode for $slot.")
        }
    }

    /**
     * Refreshes a slot's joined-group count via `POST /account/refresh-joined` and
     * sets the displayed count to the returned value (R7.8). When the Backend
     * deferred the scan (`queued`), the count is left for the realtime `state` event.
     */
    fun refreshJoined(slot: String) = runSlotAction(slot) {
        when (val result = accountsRepository.refreshJoined(slot)) {
            is NetworkResult.Success -> {
                if (result.data.success) {
                    if (!result.data.queued) {
                        val count = if (result.data.joinedGroups > 0) {
                            result.data.joinedGroups
                        } else {
                            result.data.joinedTotal
                        }
                        updateAccount(slot) { it.copy(joinedGroupCount = count) }
                        SlotResult.Ok("Joined count updated for $slot.")
                    } else {
                        SlotResult.Ok("Refresh queued for $slot.")
                    }
                } else {
                    SlotResult.Fail(result.data.error ?: "Could not refresh $slot.")
                }
            }

            is NetworkResult.Error -> SlotResult.Fail(authMessage(result, "Could not refresh $slot."))
            else -> SlotResult.Fail("Could not refresh $slot.")
        }
    }

    /**
     * Provisions a new account slot via `POST /accounts/provision-slot` and adds the
     * returned slot to the displayed list (R7.9); adds nothing on failure (R7.10).
     */
    fun provisionSlot() {
        _uiState.update { it.copy(isProvisioning = true, provisionError = null) }
        viewModelScope.launch {
            when (val result = accountsRepository.provisionSlot()) {
                is NetworkResult.Success -> {
                    val body = result.data
                    val newSlot = body.slot
                    if (body.status.equals("error", ignoreCase = true) || newSlot.isNullOrBlank()) {
                        _uiState.update {
                            it.copy(isProvisioning = false, provisionError = body.message ?: "Provisioning failed.")
                        }
                    } else {
                        if (currentAccounts.none { it.slot == newSlot }) {
                            currentAccounts = currentAccounts + AccountSlot.from(slot = newSlot)
                        }
                        _uiState.update {
                            it.copy(
                                isProvisioning = false,
                                accounts = ViewState.Content(currentAccounts),
                                successMessage = "Provisioned $newSlot.",
                            )
                        }
                    }
                }

                is NetworkResult.Error -> _uiState.update {
                    it.copy(isProvisioning = false, provisionError = authMessage(result, "Provisioning failed."))
                }

                else -> _uiState.update {
                    it.copy(isProvisioning = false, provisionError = "Provisioning failed.")
                }
            }
        }
    }

    /**
     * Clears a shutdown-list entry via `POST /account/{slot}/shutdown/clear` and
     * removes it from the displayed shutdown list on success (R7.12).
     */
    fun clearShutdown(slot: String) {
        viewModelScope.launch {
            when (val result = accountsRepository.clearShutdown(slot)) {
                is NetworkResult.Success -> {
                    val status = result.data.status
                    if (status.equals("ok", ignoreCase = true) || status.equals("not_found", ignoreCase = true)) {
                        _uiState.update {
                            it.copy(
                                shutdownEntries = it.shutdownEntries.filterNot { entry -> entry.slot == slot },
                                successMessage = "Cleared shutdown for $slot.",
                            )
                        }
                    } else {
                        _uiState.update { it.copy(actionError = result.data.message ?: "Could not clear shutdown for $slot.") }
                    }
                }

                is NetworkResult.Error -> _uiState.update {
                    it.copy(actionError = authMessage(result, "Could not clear shutdown for $slot."))
                }

                else -> _uiState.update { it.copy(actionError = "Could not clear shutdown for $slot.") }
            }
        }
    }

    /** Clears the slot-scoped error indication for [slot] (e.g. after the user edits the field). */
    fun dismissSlotError(slot: String) {
        _uiState.update { it.copy(slotErrors = it.slotErrors - slot) }
    }

    /** Clears the transient provisioning error. */
    fun dismissProvisionError() {
        _uiState.update { it.copy(provisionError = null) }
    }

    /** Clears the transient shutdown-clear error. */
    fun dismissActionError() {
        _uiState.update { it.copy(actionError = null) }
    }

    /** Clears the success confirmation once it has been shown (R25.3). */
    fun dismissSuccessMessage() {
        _uiState.update { it.copy(successMessage = null) }
    }

    /**
     * Reflects a start/stop response: on a non-`error` token sets the displayed
     * status to the token (R7.3); an `error` token leaves the status unchanged and
     * surfaces a slot-scoped error (R7.4).
     */
    private fun reflectActionStatus(slot: String, status: String?, message: String?, verb: String): SlotResult {
        if (status.equals("error", ignoreCase = true)) {
            return SlotResult.Fail(message ?: "Could not $verb $slot.")
        }
        status?.takeIf { it.isNotBlank() }?.let { token ->
            updateAccount(slot) { it.copy(status = token) }
        }
        return SlotResult.Ok(null)
    }

    /**
     * Runs a per-slot [action], marking [slot] busy for the duration, clearing its
     * prior error first, and recording the outcome (slot-scoped error on failure,
     * optional success confirmation on success).
     */
    private fun runSlotAction(slot: String, action: suspend () -> SlotResult) {
        _uiState.update { it.copy(busySlots = it.busySlots + slot, slotErrors = it.slotErrors - slot) }
        viewModelScope.launch {
            val outcome = action()
            _uiState.update { state ->
                val errors = when (outcome) {
                    is SlotResult.Fail -> state.slotErrors + (slot to outcome.message)
                    is SlotResult.Ok -> state.slotErrors - slot
                }
                state.copy(
                    busySlots = state.busySlots - slot,
                    slotErrors = errors,
                    successMessage = (outcome as? SlotResult.Ok)?.message ?: state.successMessage,
                )
            }
        }
    }

    /**
     * Applies [transform] to the row for [slot] (if present) and publishes the
     * updated content. Keeps [currentAccounts] and the displayed [ViewState.Content]
     * in lockstep so per-account reflections survive subsequent updates.
     */
    private fun updateAccount(slot: String, transform: (AccountSlot) -> AccountSlot) {
        currentAccounts = currentAccounts.map { if (it.slot == slot) transform(it) else it }
        _uiState.update { it.copy(accounts = ViewState.Content(currentAccounts)) }
    }

    /**
     * Produces a user-facing error message, surfacing an explicit authorization
     * error for an HTTP 403 (R4.6) and otherwise the slot-scoped [fallback].
     */
    private fun <T> authMessage(error: NetworkResult.Error<T>, fallback: String): String =
        if (NetworkErrorClassifier.isForbidden(error.httpStatus)) {
            "Not permitted: this action requires Admin access."
        } else {
            fallback
        }

    /** Internal outcome of a per-slot action: success (with optional message) or failure. */
    private sealed interface SlotResult {
        data class Ok(val message: String?) : SlotResult
        data class Fail(val message: String) : SlotResult
    }
}
