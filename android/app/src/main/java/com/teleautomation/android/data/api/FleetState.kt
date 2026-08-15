package com.teleautomation.android.data.api

import com.teleautomation.android.core.SuccessRate
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Kotlinx-serializable DTO for the Backend `GET /state` payload that backs the
 * fleet dashboard (R6.1, R6.2, R6.7).
 *
 * ### Faithful to the real Backend, not the simplified design model
 *
 * The design's `FleetState` sketched flat top-level fields (`accountCount`,
 * `runningCount`, `restingCount`, `postsSent`, `postsAttempted`, `inboxNew`,
 * `nextCycleEpochMillis`). The **actual** `/state` JSON
 * (`services/account_manager.py` `build_ui_state`) does not expose those as
 * top-level fields. Instead it returns the per-account map [accountStates] plus a
 * few active-account summary fields, and the dashboard figures are *derived* from
 * the per-account map — exactly as the Web_App does in
 * `dashboard/src/utils/globalStats.js` (`aggregateFleetStats`).
 *
 * This DTO therefore deserializes the **real** top-level fields and computes the
 * dashboard aggregates as pure properties below. Deviations from the design model,
 * all driven by the real Backend shape:
 *  - **No flat counts.** [accountCount], [runningCount], [restingCount],
 *    [postsSent], [postsAttempted], and [successRatePct] are derived from
 *    [accountStates] (see each property).
 *  - **`shutdown_list` is a map, not a list.** `list_shutdowns()` returns an object
 *    keyed by slot, so [shutdownList] is a `Map<String, ShutdownEntry>`.
 *  - **No `inbox-new` in `/state`.** The inbox unread total is served by the Inbox
 *    module (`GET /inbox`, R11.1) and combined at the dashboard layer (task 9.7);
 *    it is intentionally absent here rather than fabricated.
 *  - **`next_cycle_in` is a relative remaining duration (seconds), per account** —
 *    not an absolute epoch timestamp. The fleet-wide countdown is the smallest
 *    positive remaining time across accounts; [nextCycleRemainingMillis] exposes it
 *    in milliseconds for the countdown formatter (task 9.3, R6.7).
 *
 * Unknown keys are ignored and missing values coerced by the lenient JSON converter
 * (`NetworkModule`), so this lean DTO keeps deserializing the large `/state` object
 * as the Backend evolves (R22.3). All fields default so a partial payload never
 * fails to decode.
 */
@Serializable
data class FleetState(
    /** Canonical list of configured Account_Slot ids (`account_slots`). */
    @SerialName("account_slots") val accountSlots: List<String> = emptyList(),

    /** Whether the *active* account is running (active-account summary field). */
    val running: Boolean = false,

    /** Size of the master group list (`total`); shown as fleet reach context. */
    val total: Int = 0,

    /** Per-account worker state, keyed by slot (`account_states`). */
    @SerialName("account_states") val accountStates: Map<String, AccountWorkerState> = emptyMap(),

    /**
     * Active accounts currently rested by the auto-shutdown rule, keyed by slot
     * (`shutdown_list`). A map (not a list) because `list_shutdowns()` returns an
     * object keyed by slot id (R7.11).
     */
    @SerialName("shutdown_list") val shutdownList: Map<String, ShutdownEntry> = emptyMap(),
) {

    /**
     * Number of accounts in the fleet (R6.1).
     *
     * Uses the canonical [accountSlots] list, falling back to the size of
     * [accountStates] if the slot list is absent from a partial payload.
     */
    val accountCount: Int
        get() = if (accountSlots.isNotEmpty()) accountSlots.size else accountStates.size

    /**
     * Number of accounts actively posting right now (R6.1).
     *
     * Derived as the count of per-account states whose `running` flag is set,
     * mirroring the Web_App's running tally.
     */
    val runningCount: Int
        get() = accountStates.values.count { it.running }

    /**
     * Number of accounts resting between cycles (R6.1).
     *
     * Derived as the count of accounts that are **not** running yet are waiting —
     * either rate-limited/sleeping (`heavy_rate_limit`) or counting down to their
     * next cycle (`next_cycle_in > 0`). This is the dashboard's coarse "resting"
     * tally; the DashboardScreen/ViewModel (task 9.7) may refine per-account status
     * using logged-in and shutdown signals.
     */
    val restingCount: Int
        get() = accountStates.values.count { state ->
            !state.running && (state.heavyRateLimit || state.nextCycleIn > 0)
        }

    /**
     * Total posts sent successfully across the fleet (`s`), summed from per-account
     * `success` counters (R6.1). This is the numerator of the success rate.
     */
    val postsSent: Int
        get() = accountStates.values.sumOf { it.success }

    /**
     * Total posts attempted across the fleet (`a`), i.e. `success + failed` summed
     * per account (R6.1). Groups skipped because they were already posted to are
     * **not** attempts and are excluded, matching the Web_App
     * (`computeSuccessRatePct`).
     */
    val postsAttempted: Int
        get() = accountStates.values.sumOf { it.success + it.failed }

    /**
     * Fleet success rate as an integer percentage in `[0, 100]` (R6.1, Property 6).
     *
     * Pure delegation to [SuccessRate.percent] over the derived [postsSent] and
     * [postsAttempted]; `0` when there have been no attempts. Kept free of any I/O
     * so task 9.2 can property-test the computation directly.
     */
    val successRatePct: Int
        get() = SuccessRate.percent(postsSent, postsAttempted)

    /**
     * Remaining time to the next fleet cycle in **milliseconds**, or `null` when no
     * account is currently counting down (R6.7).
     *
     * Derived as the smallest positive per-account `next_cycle_in` (seconds)
     * converted to milliseconds, so the dashboard countdown reflects the soonest
     * account to wake. Feeds the cycle countdown formatter (task 9.3).
     */
    val nextCycleRemainingMillis: Long?
        get() = accountStates.values
            .map { it.nextCycleIn }
            .filter { it > 0 }
            .minOrNull()
            ?.let { it.toLong() * 1000L }

    /**
     * Computes the dashboard figures scoped to the selected [WorkspaceMode] (R6.3).
     *
     * The dashboard's Workspace_Mode selector narrows every displayed figure to the
     * accounts associated with the chosen mode, mirroring the Web_App scope selector:
     *  - [WorkspaceMode.FLEET] aggregates **all** accounts — identical to the
     *    fleet-wide derived properties above (so the FLEET figures and the top-level
     *    [accountCount]/[runningCount]/… stay in lockstep).
     *  - [WorkspaceMode.FORWARDING] / [WorkspaceMode.CAMPAIGN] restrict the
     *    aggregation to accounts whose per-account [AccountWorkerState.postingMode]
     *    resolves to that [PostingMode] (R6.2/R6.3).
     *
     * Pure and side-effect-free so the DashboardViewModel (task 9.7) can recompute
     * figures whenever the mode changes without re-fetching `/state`, and so the
     * filtering is testable on the plain JVM. Posts-attempted and success rate reuse
     * the same `success + failed` definition as the fleet-wide properties, so a
     * filtered success rate stays within `[0, 100]` (Property 6).
     */
    fun figuresFor(mode: WorkspaceMode): DashboardFigures {
        val selected: Collection<AccountWorkerState> = when (mode) {
            WorkspaceMode.FLEET -> accountStates.values
            WorkspaceMode.FORWARDING ->
                accountStates.values.filter { it.postingMode == PostingMode.FORWARDING }
            WorkspaceMode.CAMPAIGN ->
                accountStates.values.filter { it.postingMode == PostingMode.CAMPAIGN }
        }

        // For the whole fleet, prefer the canonical slot list (so configured-but-idle
        // accounts still count); for a filtered mode, count only the matching states.
        val count = when (mode) {
            WorkspaceMode.FLEET -> accountCount
            else -> selected.size
        }

        val sent = selected.sumOf { it.success }
        val attempted = selected.sumOf { it.success + it.failed }
        val nextCycle = selected
            .map { it.nextCycleIn }
            .filter { it > 0 }
            .minOrNull()
            ?.let { it.toLong() * 1000L }

        return DashboardFigures(
            accountCount = count,
            runningCount = selected.count { it.running },
            restingCount = selected.count { !it.running && (it.heavyRateLimit || it.nextCycleIn > 0) },
            postsSent = sent,
            postsAttempted = attempted,
            successRatePct = SuccessRate.percent(sent, attempted),
            nextCycleRemainingMillis = nextCycle,
        )
    }
}

/**
 * The dashboard summary figures for a single [WorkspaceMode] (R6.1, R6.3).
 *
 * Produced purely from a [FleetState] via [FleetState.figuresFor]. `inbox-new` is
 * intentionally **not** part of this model: the inbox unread total is served by the
 * Inbox module (`GET /inbox`, R11.1), not `/state`, so it is combined at the
 * dashboard layer (the DashboardViewModel/Screen accept it as a separate wired-in
 * input, defaulting to `0` until the Inbox realtime feed supplies it).
 *
 * @property accountCount number of accounts in scope (R6.1).
 * @property runningCount accounts actively posting in scope (R6.1).
 * @property restingCount accounts resting between cycles in scope (R6.1).
 * @property postsSent successful posts summed across the scoped accounts (R6.1).
 * @property postsAttempted attempts (`success + failed`) across the scoped accounts.
 * @property successRatePct integer success rate in `[0, 100]` (R6.1, Property 6).
 * @property nextCycleRemainingMillis soonest positive next-cycle remaining time in
 *   milliseconds across the scoped accounts, or `null` when none is counting down
 *   (drives the per-second countdown, R6.7).
 */
data class DashboardFigures(
    val accountCount: Int,
    val runningCount: Int,
    val restingCount: Int,
    val postsSent: Int,
    val postsAttempted: Int,
    val successRatePct: Int,
    val nextCycleRemainingMillis: Long?,
)

/**
 * Per-account worker state nested under `account_states[slot]` in `GET /state`
 * (`workers/account_state.py` `to_dict`).
 *
 * Only the fields the dashboard aggregates are modeled; every other key in the rich
 * per-account object is ignored by the lenient converter. All fields default so a
 * partial entry decodes cleanly.
 */
@Serializable
data class AccountWorkerState(
    /** Whether this account's worker is running (campaign or forwarding). */
    val running: Boolean = false,

    /** Successful posts for this account in the current window. */
    val success: Int = 0,

    /** Failed posts for this account in the current window. */
    val failed: Int = 0,

    /** Coarse worker status string (e.g. `running`, `stopped`, `sleeping`). */
    val status: String = "",

    /** Remaining seconds until this account's next cycle; `0` when not waiting. */
    @SerialName("next_cycle_in") val nextCycleIn: Int = 0,

    /** Whether this account is paused by a heavy Telegram rate limit (resting). */
    @SerialName("heavy_rate_limit") val heavyRateLimit: Boolean = false,

    /**
     * Raw per-account posting-mode token from `account_states[slot].posting_mode`
     * (`workers/account_state.py`: `campaign | forwarding | both | none`). Kept as
     * the raw string so a composite/unknown token never fails the decode; resolve
     * it through [postingMode] for Workspace_Mode filtering (R6.3).
     */
    @SerialName("posting_mode") val postingModeRaw: String = "campaign",
) {

    /**
     * This account's [PostingMode], folded from [postingModeRaw] via
     * [PostingMode.fromBackend] (so `"both"` resolves to [PostingMode.FORWARDING]
     * and any unrecognized/blank token resolves to [PostingMode.CAMPAIGN]). Drives
     * the dashboard Workspace_Mode aggregation in [FleetState.figuresFor] (R6.3).
     */
    val postingMode: PostingMode
        get() = PostingMode.fromBackend(postingModeRaw)
}

/**
 * A single auto-shutdown entry from `shutdown_list[slot]` in `GET /state`
 * (`core/account_shutdown.py` `_entry`), describing an account rested by the
 * no-recent-posts rule (R7.11).
 *
 * Epoch fields are seconds (Python `time.time()`); modeled as nullable [Double] to
 * tolerate absent values in a partial payload.
 */
@Serializable
data class ShutdownEntry(
    /** The rested Account_Slot id. */
    val slot: String = "",

    /** Epoch seconds when the account was shut down (`shutdown_at`). */
    @SerialName("shutdown_at") val shutdownAt: Double? = null,

    /** Epoch seconds when the account is scheduled to resume (`resume_at`). */
    @SerialName("resume_at") val resumeAt: Double? = null,

    /** Machine-readable reason code (e.g. `no_post_6h`). */
    val reason: String = "",

    /** Whether the account was running when it was rested. */
    @SerialName("was_running") val wasRunning: Boolean = true,

    /** Epoch seconds of the last successful send before shutdown, if known. */
    @SerialName("last_send_at") val lastSendAt: Double? = null,
)
