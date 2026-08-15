package com.teleautomation.android.data.api

/**
 * Composite UI/domain model for a single account row on the Accounts screen
 * (design `AccountSlot`, R7.1).
 *
 * ### Why this is a domain model, not a wire DTO
 *
 * The design presented `AccountSlot(slot, displayName, status, joinedGroupCount,
 * postingMode)` as though it were the `GET /accounts` payload. In reality
 * `/accounts` returns only the slot roster ([AccountsResponse]); the four display
 * fields are sourced from three different Backend responses (see [AccountsDtos]
 * KDoc). This model is therefore *assembled* at the repository/ViewModel layer from
 * those sources rather than deserialized directly, keeping the screen model faithful
 * to the design while the wire DTOs stay faithful to the Backend.
 *
 * @property slot the Account_Slot id (from [AccountsResponse.accountSlots]).
 * @property displayName dashboard label (from [AccountInfo.displayName]; falls back
 *   to the slot id when unset). Edited within `[1,64]` chars (R7.5).
 * @property status coarse worker status (from `GET /state`
 *   [AccountWorkerState.status]; updated to the per-account start/stop response
 *   token after those actions, R7.3).
 * @property joinedGroupCount joined-group count (from [AccountInfo.joinedGroups] /
 *   refresh-joined, R7.8).
 * @property postingMode the account's posting mode (from `GET
 *   /account/{slot}/posting-mode`, R7.7).
 * @property subscription whether the slot is a subscription account
 *   (from [AccountsResponse.subscriptionSlots]).
 */
data class AccountSlot(
    val slot: String,
    val displayName: String,
    val status: String,
    val joinedGroupCount: Int,
    val postingMode: PostingMode,
    val subscription: Boolean = false,
) {
    companion object {
        /**
         * Assembles an [AccountSlot] from the per-source Backend data for one slot.
         *
         * Used by the Accounts repository/ViewModel to merge the roster
         * ([AccountsResponse]) with each slot's worker state ([AccountWorkerState]
         * from `GET /state`), stored info ([AccountInfo]), and posting mode. Any
         * absent source degrades gracefully: the display name falls back to the
         * slot id, status to empty, joined count to `0`, and posting mode to the
         * Backend default ([PostingMode.CAMPAIGN]).
         */
        fun from(
            slot: String,
            info: AccountInfo? = null,
            workerState: AccountWorkerState? = null,
            postingMode: PostingMode = PostingMode.CAMPAIGN,
            subscription: Boolean = false,
        ): AccountSlot = AccountSlot(
            slot = slot,
            displayName = info?.displayName?.takeIf { it.isNotBlank() } ?: slot,
            status = workerState?.status.orEmpty(),
            joinedGroupCount = info?.joinedGroups ?: 0,
            postingMode = postingMode,
            subscription = subscription,
        )
    }
}
