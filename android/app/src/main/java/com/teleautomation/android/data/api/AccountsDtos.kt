package com.teleautomation.android.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Kotlinx-serializable DTOs for the Backend account/fleet-management routes (R7).
 *
 * Field names mirror the Backend JSON exactly (verified against `server.py` and
 * `core/posting_mode.py` / `core/account_info_store.py`); snake_case wire names are
 * bound with [SerialName] so the Kotlin side stays idiomatic camelCase. All DTOs
 * declare defaults so the lenient JSON converter (unknown keys ignored, missing
 * values coerced) keeps deserializing as the Backend evolves (R22.3). No new
 * endpoints are introduced — every shape maps 1:1 to a route the Web_App already
 * calls (R23.2).
 *
 * ### Reality check: `GET /accounts` does NOT return per-account detail
 *
 * The design sketched an `AccountSlot` DTO with `displayName`, `status`,
 * `joinedGroupCount`, and `postingMode` as if `/accounts` returned them. It does
 * not. The real `list_accounts()` handler returns only the slot *roster*:
 * `{ account_slots, subscription_slots, count, code_version }` ([AccountsResponse]).
 * The per-account display fields live in three other places, exactly as the
 * Web_App assembles them:
 *  - **display name + joined-group count** come from each account's stored info
 *    ([AccountInfo], surfaced by `/account/{slot}/display-name` and
 *    `/account/refresh-joined`, and embedded in `GET /state`);
 *  - **status** comes from the per-account worker state in `GET /state`
 *    ([AccountWorkerState] in `FleetState`);
 *  - **posting mode** comes from `GET /account/{slot}/posting-mode`
 *    ([PostingModeResponse]).
 *
 * The composite UI row the design calls `AccountSlot` is therefore assembled at the
 * repository/ViewModel layer from these sources; see [AccountSlot].
 */

/**
 * Response of `GET /accounts` (`server.py` `list_accounts`), R7.1.
 *
 * Shape: `{ account_slots, subscription_slots, count, code_version }`. This is the
 * canonical slot roster only — it carries no display name, status, joined-group
 * count, or posting mode (those are sourced from `/state`, `/account/{slot}/...`).
 */
@Serializable
data class AccountsResponse(
    /** Canonical list of configured Account_Slot ids. */
    @SerialName("account_slots") val accountSlots: List<String> = emptyList(),

    /** Slots classified as subscription (channel-focused) accounts. */
    @SerialName("subscription_slots") val subscriptionSlots: List<String> = emptyList(),

    /** Number of configured slots. */
    val count: Int = 0,

    /** Backend code version tag (diagnostic only). */
    @SerialName("code_version") val codeVersion: String? = null,
)

/**
 * Per-account stored info as returned inside `/account/{slot}/display-name` (the
 * `account_info` object) and mirrored from `core/account_info_store.py`.
 *
 * Only the fields the Accounts UI needs are modeled (R7.1, R7.5, R7.8); every other
 * key is ignored by the lenient converter. Joined counts default to `0` so a
 * partial entry decodes cleanly.
 */
@Serializable
data class AccountInfo(
    /** Telegram phone number bound to the slot, when logged in. */
    val phone: String? = null,

    /** Dashboard display label (Backend caps this at 48 characters). */
    @SerialName("display_name") val displayName: String? = null,

    /** Joined group count for this account. */
    @SerialName("joined_groups") val joinedGroups: Int = 0,

    /** Joined channel count for this account. */
    @SerialName("joined_channels") val joinedChannels: Int = 0,

    /** Combined joined groups + channels. */
    @SerialName("joined_total") val joinedTotal: Int = 0,

    /** ISO timestamp of the last joined-count refresh, when known. */
    @SerialName("joined_updated_at") val joinedUpdatedAt: String? = null,
)

/**
 * Response of `POST /account/{slot}/start` and `POST /account/{slot}/stop`
 * (`server.py` `start_account` / `stop_account`), R7.3.
 *
 * The Backend returns a `status` token — `"started"`, `"stopped"`,
 * `"already_running"`, or `"error"` (with a `message`) — plus the affected `slot`
 * and `feature`. The stop handler additionally splats the full UI state into the
 * body; those extra keys are ignored, since the authoritative post-action status is
 * delivered via the realtime `state` event (R22.5). The caller sets the displayed
 * status from [status] (R7.3); on an error/non-success the status is left unchanged
 * (R7.4).
 */
@Serializable
data class AccountActionResponse(
    /** Backend status token (`started` / `stopped` / `already_running` / `error`). */
    val status: String? = null,

    /** The affected Account_Slot id. */
    val slot: String? = null,

    /** The feature acted on (`all` / `campaign` / `forwarding`). */
    val feature: String? = null,

    /** Human-readable detail, populated on the error path. */
    val message: String? = null,
)

/**
 * Request body for `POST /account/{slot}/display-name`: `{ display_name }` (R7.5).
 *
 * Client-side validation (the bounded `[1,64]` display-name validator, task 10.2)
 * gates this call so an empty/over-length name is never submitted (R7.6). Note the
 * Backend itself enforces a stricter max of 48 characters and truncates beyond it;
 * a name in `(48, 64]` is accepted by the client validator but stored truncated by
 * the Backend, and the UI reflects the returned [DisplayNameResponse.accountInfo].
 */
@Serializable
data class DisplayNameRequest(
    @SerialName("display_name") val displayName: String,
)

/**
 * Response of `POST /account/{slot}/display-name`
 * (`server.py` `set_account_display_name`), R7.5.
 *
 * Shape: `{ success, account_info }` on success, or `{ success: false, error }` on
 * rejection (invalid slot, empty/too-long name, or not logged in). The caller shows
 * the name from [accountInfo] on success (R7.5).
 */
@Serializable
data class DisplayNameResponse(
    /** Whether the rename was applied. */
    val success: Boolean = false,

    /** The updated stored info (display name + joined counts) on success. */
    @SerialName("account_info") val accountInfo: AccountInfo? = null,

    /** Failure reason when [success] is false. */
    val error: String? = null,
)

/**
 * Request body for `POST /account/{slot}/posting-mode` (R7.7).
 *
 * Mirrors `set_posting_mode_endpoint`: the Backend accepts any subset of `mode`,
 * `campaign_enabled`, `forwarding_enabled`, `forward_source_type`, and
 * `forward_dispatch`; at least one must be present. The toggle fields are nullable
 * so only the changed fields are sent (omitted nulls are dropped by the converter),
 * matching the Web_App's partial updates.
 */
@Serializable
data class PostingModeRequest(
    /** Legacy mode token (`"campaign"` / `"forwarding"` / `"both"` / `"none"`). */
    val mode: String? = null,

    /** Enable/disable the campaign poster. */
    @SerialName("campaign_enabled") val campaignEnabled: Boolean? = null,

    /** Enable/disable the forwarding poster. */
    @SerialName("forwarding_enabled") val forwardingEnabled: Boolean? = null,

    /** Forward source type (e.g. `template` / `url`). */
    @SerialName("forward_source_type") val forwardSourceType: String? = null,

    /** Forward dispatch strategy token. */
    @SerialName("forward_dispatch") val forwardDispatch: String? = null,
)

/**
 * Response of `GET`/`POST /account/{slot}/posting-mode`
 * (`server.py` `get_posting_mode` / `set_posting_mode_endpoint`), R7.7.
 *
 * Shape: `{ status, campaign_enabled, forwarding_enabled, mode, forwarding }`. The
 * displayed [PostingMode] is resolved from [mode] via [PostingMode.fromBackend]
 * (which folds composite `"both"`/`"none"` tokens), exposed as [postingMode]. The
 * nested `forwarding` object is not needed by the Accounts list and is ignored.
 */
@Serializable
data class PostingModeResponse(
    /** Backend status token (`ok` / `error`). */
    val status: String? = null,

    /** Whether the campaign poster is enabled. */
    @SerialName("campaign_enabled") val campaignEnabled: Boolean = false,

    /** Whether the forwarding poster is enabled. */
    @SerialName("forwarding_enabled") val forwardingEnabled: Boolean = false,

    /** Legacy mode label (`campaign` / `forwarding` / `both` / `none`). */
    val mode: String? = null,

    /** Error detail when [status] is `error`. */
    val message: String? = null,
) {
    /** The single posting mode the Accounts UI displays, resolved from [mode]. */
    val postingMode: PostingMode
        get() = PostingMode.fromBackend(mode)
}

/**
 * Request body for `POST /account/refresh-joined`: `{ slot }` (R7.8).
 *
 * The slot is sent in the body (not the path) — this is a fleet-level route that
 * takes the target slot as a payload field, falling back to the active account on
 * the Backend when omitted.
 */
@Serializable
data class RefreshJoinedRequest(
    val slot: String,
)

/**
 * Response of `POST /account/refresh-joined`
 * (`server.py` `refresh_joined_counts`), R7.8.
 *
 * Shape on success: `{ success, slot, joined_groups, joined_channels, joined_total,
 * joined_updated_at }`, plus `{ queued, message }` when the account was running and
 * the scan was deferred. On failure: `{ success: false, error }`. The caller sets
 * the displayed joined-group count from [joinedGroups]/[joinedTotal] (R7.8); when
 * [queued] is true the count is refreshed later via the realtime `state` event.
 */
@Serializable
data class RefreshJoinedResponse(
    /** Whether the refresh succeeded (or was successfully queued). */
    val success: Boolean = false,

    /** The refreshed Account_Slot id. */
    val slot: String? = null,

    /** Joined group count after the scan. */
    @SerialName("joined_groups") val joinedGroups: Int = 0,

    /** Joined channel count after the scan. */
    @SerialName("joined_channels") val joinedChannels: Int = 0,

    /** Combined joined groups + channels after the scan. */
    @SerialName("joined_total") val joinedTotal: Int = 0,

    /** ISO timestamp of this refresh. */
    @SerialName("joined_updated_at") val joinedUpdatedAt: String? = null,

    /** True when the account was running and the scan was deferred. */
    val queued: Boolean = false,

    /** Human-readable detail (deferral note or failure reason). */
    val message: String? = null,

    /** Failure reason when [success] is false. */
    val error: String? = null,
)

/**
 * Response of `POST /accounts/provision-slot`
 * (`server.py` `provision_account_slot`), R7.9.
 *
 * Shape: `{ status, slot, account_slots, message }` plus the splatted UI state
 * (ignored). The caller adds [slot] to the displayed list and may refresh the
 * roster from [accountSlots] (R7.9); on a non-success [status] no entry is added
 * (R7.10).
 */
@Serializable
data class ProvisionSlotResponse(
    /** Backend status token (`ok` / `error`). */
    val status: String? = null,

    /** The newly provisioned Account_Slot id. */
    val slot: String? = null,

    /** The full slot roster after provisioning. */
    @SerialName("account_slots") val accountSlots: List<String> = emptyList(),

    /** Human-readable detail (e.g. login instruction or failure reason). */
    val message: String? = null,
)

/**
 * Response of `POST /account/{slot}/shutdown/clear`
 * (`server.py` `clear_account_shutdown`), R7.12.
 *
 * Shape: `{ status, slot }` plus the splatted UI state (ignored). [status] is
 * `"ok"` when the entry was cleared, `"not_found"` when no shutdown existed, or
 * `"error"` for an invalid slot. The caller removes the entry from the displayed
 * shutdown list on success (R7.12).
 */
@Serializable
data class ShutdownClearResponse(
    /** Backend status token (`ok` / `not_found` / `error`). */
    val status: String? = null,

    /** The affected Account_Slot id. */
    val slot: String? = null,

    /** Error detail when [status] is `error`. */
    val message: String? = null,
)
