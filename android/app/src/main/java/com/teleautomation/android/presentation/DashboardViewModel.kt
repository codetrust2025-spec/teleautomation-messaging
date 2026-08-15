package com.teleautomation.android.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.teleautomation.android.core.ConfirmationGate
import com.teleautomation.android.core.ConfirmationOutcome
import com.teleautomation.android.core.CycleCountdown
import com.teleautomation.android.core.CycleCountdownFormatter
import com.teleautomation.android.core.NetworkResult
import com.teleautomation.android.core.ViewState
import com.teleautomation.android.core.ViewStateSelector
import com.teleautomation.android.data.api.DashboardFigures
import com.teleautomation.android.data.api.FleetState
import com.teleautomation.android.data.api.WorkspaceMode
import com.teleautomation.android.data.repo.StateRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Immutable UI state for the Dashboard (R6).
 *
 * The screen renders this and forwards intents back to the [DashboardViewModel]
 * (MVVM); it owns no business logic of its own.
 *
 * @property figures the transient state of the fleet figures for the currently
 *   [selectedMode], derived from the latest `/state` result via
 *   [ViewStateSelector]. On an error the last successfully displayed figures are
 *   retained behind the error indication (R6.2, R25.4).
 * @property selectedMode the active Workspace_Mode filter (R6.3).
 * @property inboxNewCount the inbox-new count combined into the dashboard summary.
 *   It originates from the Inbox module (`GET /inbox`, R11.1), **not** `/state`, so
 *   it is supplied as a wired-in input and defaults to `0` until the inbox feed
 *   provides it (see [setInboxNewCount]).
 * @property countdown the decomposed per-second countdown to the next fleet cycle
 *   while accounts in scope are sleeping, or `null` when nothing is counting down
 *   (R6.7).
 * @property isRefreshing whether a pull-to-refresh re-fetch is in flight (R6.10).
 * @property isActionInFlight whether a start-all / stop-all / reach-reset call is in
 *   flight (used to disable the controls and avoid duplicate submissions).
 * @property actionError a transient error indication for a failed start/stop/reset
 *   action; the displayed figures are left unchanged (R6.6); `null` when none.
 * @property successMessage a confirmation message for a completed action, or `null`.
 * @property showResetDialog whether the reach-reset confirmation dialog is visible
 *   (R6.8, R6.9).
 */
data class DashboardUiState(
    val figures: ViewState<DashboardFigures> = ViewState.Loading,
    val selectedMode: WorkspaceMode = WorkspaceMode.FLEET,
    val inboxNewCount: Int = 0,
    val countdown: CycleCountdown? = null,
    val isRefreshing: Boolean = false,
    val isActionInFlight: Boolean = false,
    val actionError: String? = null,
    val successMessage: String? = null,
    val showResetDialog: Boolean = false,
)

/**
 * Presentation-layer ViewModel for the Dashboard / fleet overview (R6.1–R6.10).
 *
 * Responsibilities:
 *  - **Fleet figures (R6.1, R6.2).** Loads `GET /state` through [StateRepository]
 *    on construction, on [refresh] (pull-to-refresh, R6.10), and after each control
 *    action. The result is mapped to a [ViewState] of [DashboardFigures] scoped to
 *    the [selectedMode]; on failure the last figures are retained unchanged
 *    (R6.2) and a retry is offered (R25.5).
 *  - **Workspace_Mode filter (R6.3).** [onModeSelected] re-derives the figures from
 *    the last fetched [FleetState] without a re-fetch via [FleetState.figuresFor].
 *  - **Start-all / stop-all (R6.4, R6.5, R6.6).** [startAll]/[stopAll] call the
 *    Backend; on success the resulting running state is reflected by re-fetching
 *    `/state` (the action responses do not carry it); on failure an error is
 *    surfaced and the figures are left unchanged.
 *  - **Per-second sleep countdown (R6.7).** A ticking job recomputes the remaining
 *    time once per second from a captured deadline using
 *    [CycleCountdownFormatter.formatClamped].
 *  - **Reach reset (R6.8, R6.9).** [requestReachReset] shows the confirmation
 *    dialog; [onReachResetOutcome] routes the outcome through [ConfirmationGate] so
 *    `POST /stats/reset` runs **only** on explicit confirm and **never** on cancel.
 *
 * The ViewModel performs no navigation and touches no Android/Compose types so it
 * stays unit-testable; the pure figures/countdown/confirmation logic lives in
 * `core` and on [FleetState].
 */
@HiltViewModel
class DashboardViewModel @Inject constructor(
    private val stateRepository: StateRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(DashboardUiState())
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    /** The most recently fetched fleet state, retained to recompute figures on mode change and to keep figures visible behind an error (R6.2, R6.3). */
    private var lastFleetState: FleetState? = null

    /** Per-second countdown ticker; cancelled/replaced whenever the deadline changes (R6.7). */
    private var countdownJob: Job? = null

    init {
        load(initial = true)
    }

    /**
     * Re-fetches fleet state for a pull-to-refresh gesture (R6.10). Keeps the
     * currently displayed figures visible (sets [DashboardUiState.isRefreshing]
     * rather than flipping to a full-screen loading state) so the refresh is
     * non-disruptive, and updates the figures on the response.
     */
    fun refresh() {
        load(initial = false)
    }

    /**
     * Re-issues the failed `/state` request (R25.5). Re-fetching `/state` is exactly
     * the original parameterless request, so this both satisfies the retry control
     * and refreshes the figures.
     */
    fun retry() {
        _uiState.update { it.copy(figures = ViewState.Loading) }
        viewModelScope.launch { applyStateResult(stateRepository.fetchState()) }
    }

    /**
     * Selects a Workspace_Mode and re-derives every displayed figure from the last
     * fetched state without a network round-trip (R6.3). When no state has been
     * fetched yet the selection is recorded and applied on the next successful load.
     */
    fun onModeSelected(mode: WorkspaceMode) {
        if (mode == _uiState.value.selectedMode) return
        _uiState.update { it.copy(selectedMode = mode) }
        val state = lastFleetState ?: return
        val figures = state.figuresFor(mode)
        _uiState.update { it.copy(figures = ViewState.Content(figures)) }
        restartCountdown(figures.nextCycleRemainingMillis)
    }

    /** Combines the inbox-new count (from the Inbox module, R11.1) into the summary. */
    fun setInboxNewCount(count: Int) {
        val safe = count.coerceAtLeast(0)
        if (safe == _uiState.value.inboxNewCount) return
        _uiState.update { it.copy(inboxNewCount = safe) }
    }

    /**
     * Starts all logged-in accounts (R6.4). On success re-fetches `/state` so the
     * displayed running state matches the Backend; on failure surfaces an error and
     * leaves the figures unchanged (R6.6).
     */
    fun startAll() {
        runFleetAction(successMessage = START_ALL_CONFIRMATION) { stateRepository.startAll() }
    }

    /**
     * Stops all accounts (R6.5). On success re-fetches `/state`; on failure surfaces
     * an error and leaves the figures unchanged (R6.6).
     */
    fun stopAll() {
        runFleetAction(successMessage = STOP_ALL_CONFIRMATION) { stateRepository.stopAll() }
    }

    /** Shows the reach-reset confirmation dialog (R6.8). */
    fun requestReachReset() {
        _uiState.update { it.copy(showResetDialog = true) }
    }

    /**
     * Routes the confirmation-dialog [outcome] through [ConfirmationGate] (R6.8,
     * R6.9): on [ConfirmationOutcome.Confirm] it calls `POST /stats/reset` and then
     * re-fetches `/state`; on [ConfirmationOutcome.Cancel] it merely dismisses the
     * dialog and the Backend is never called.
     */
    fun onReachResetOutcome(outcome: ConfirmationOutcome) {
        _uiState.update { it.copy(showResetDialog = false) }
        ConfirmationGate.dispatch(outcome) {
            runFleetAction(successMessage = RESET_CONFIRMATION) { stateRepository.resetStats() }
        }
    }

    /** Clears the transient action error indication (R6.6). */
    fun dismissActionError() {
        _uiState.update { it.copy(actionError = null) }
    }

    /** Clears the success confirmation once it has been shown (R25.3). */
    fun dismissSuccessMessage() {
        _uiState.update { it.copy(successMessage = null) }
    }

    /**
     * Fetches `/state` and applies the result. [initial] distinguishes the first
     * load (which shows the full-screen loading state) from a pull-to-refresh, which
     * keeps the current figures and toggles [DashboardUiState.isRefreshing] (R6.10).
     */
    private fun load(initial: Boolean) {
        _uiState.update {
            if (initial) {
                it.copy(figures = ViewState.Loading)
            } else {
                it.copy(isRefreshing = true)
            }
        }
        viewModelScope.launch {
            val result = stateRepository.fetchState()
            applyStateResult(result)
            _uiState.update { it.copy(isRefreshing = false) }
        }
    }

    /**
     * Maps a `/state` [result] into the figures view-state for the current mode,
     * retaining the last figures behind an error (R6.2), and (re)starts the
     * countdown from the fresh figures (R6.7).
     */
    private fun applyStateResult(result: NetworkResult<FleetState>) {
        val mode = _uiState.value.selectedMode
        if (result is NetworkResult.Success) {
            lastFleetState = result.data
            val figures = result.data.figuresFor(mode)
            _uiState.update { it.copy(figures = ViewState.Content(figures)) }
            restartCountdown(figures.nextCycleRemainingMillis)
            return
        }

        // Error / (defensively) Empty|Loading: project the result onto the figures
        // type so the retry closure stays type-correct, and retain the last
        // displayed figures behind the error indication (R6.2).
        val retained = lastFleetState?.figuresFor(mode)
        _uiState.update {
            it.copy(figures = ViewStateSelector.select(result.toFigures(mode), previousContent = retained))
        }
    }

    /**
     * Projects a `/state` [NetworkResult] onto the [DashboardFigures] type for the
     * given [mode], deriving the figures on success and recursively re-projecting
     * the retry closure on error so the resulting [NetworkResult] of figures carries
     * a faithful, type-correct retry (R26.5, R26.6).
     */
    private fun NetworkResult<FleetState>.toFigures(mode: WorkspaceMode): NetworkResult<DashboardFigures> =
        when (this) {
            is NetworkResult.Success -> NetworkResult.Success(data.figuresFor(mode))
            is NetworkResult.Error -> NetworkResult.Error(
                kind = kind,
                message = message,
                retry = { retry().toFigures(mode) },
                httpStatus = httpStatus,
            )
            NetworkResult.Empty -> NetworkResult.Empty
            NetworkResult.Loading -> NetworkResult.Loading
        }

    /**
     * Executes a fleet-control [action], reflecting the resulting state by
     * re-fetching `/state` on success (R6.4, R6.5) and surfacing an error while
     * leaving the figures unchanged on failure (R6.6).
     */
    private fun runFleetAction(
        successMessage: String,
        action: suspend () -> NetworkResult<*>,
    ) {
        _uiState.update { it.copy(isActionInFlight = true, actionError = null, successMessage = null) }
        viewModelScope.launch {
            when (val result = action()) {
                is NetworkResult.Error -> {
                    _uiState.update {
                        it.copy(isActionInFlight = false, actionError = result.message)
                    }
                }

                else -> {
                    // Reflect the Backend's resulting running state via a refresh
                    // rather than the action response body (R6.4, R6.5, R22.5).
                    val refreshed = stateRepository.fetchState()
                    applyStateResult(refreshed)
                    _uiState.update {
                        it.copy(isActionInFlight = false, successMessage = successMessage)
                    }
                }
            }
        }
    }

    /**
     * (Re)starts the per-second countdown to the next cycle (R6.7).
     *
     * Captures a deadline `now + remainingMillis` and ticks once per second,
     * recomputing the remaining time with [CycleCountdownFormatter.formatClamped]
     * until it reaches zero. A `null` [remainingMillis] means nothing is sleeping in
     * scope, so the countdown is cleared and no ticker runs.
     */
    private fun restartCountdown(remainingMillis: Long?) {
        countdownJob?.cancel()
        countdownJob = null

        if (remainingMillis == null) {
            _uiState.update { it.copy(countdown = null) }
            return
        }

        val deadline = nowMillis() + remainingMillis
        countdownJob = viewModelScope.launch {
            while (true) {
                val remaining = deadline - nowMillis()
                _uiState.update {
                    it.copy(countdown = CycleCountdownFormatter.formatClamped(remaining))
                }
                if (remaining <= 0L) break
                delay(COUNTDOWN_TICK_MILLIS)
            }
        }
    }

    /** Current wall-clock time; isolated so the countdown deadline math is simple. */
    private fun nowMillis(): Long = System.currentTimeMillis()

    private companion object {
        /** One-second cadence for the sleep countdown (R6.7: "at least once per second"). */
        const val COUNTDOWN_TICK_MILLIS = 1_000L

        const val START_ALL_CONFIRMATION = "Starting all accounts."
        const val STOP_ALL_CONFIRMATION = "Stopping all accounts."
        const val RESET_CONFIRMATION = "Reach counters reset."
    }
}
