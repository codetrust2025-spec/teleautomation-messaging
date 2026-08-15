package com.teleautomation.android.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The per-account operating mode (R7.7, design `Posting_Mode`).
 *
 * The Backend reports the posting mode as a lowercase string token
 * (`"campaign"` / `"forwarding"`; see `core/posting_mode.py` `MODE_CAMPAIGN` /
 * `MODE_FORWARDING`). The design models the two posting modes the Android UI
 * exposes; the Backend additionally recognizes the composite tokens `"both"` and
 * `"none"`, which [fromBackend] folds onto the closest single mode so an unexpected
 * value never crashes a decode.
 *
 * Defined in `data.api` alongside the auth [Role] because both the account DTOs
 * (task 10) and the dashboard scope filtering consume it. Prefer [fromBackend] over
 * direct enum deserialization for state payloads, since the raw token may be a
 * composite value outside this enum's `@SerialName` set.
 */
@Serializable
enum class PostingMode {
    @SerialName("forwarding")
    FORWARDING,

    @SerialName("campaign")
    CAMPAIGN,
    ;

    companion object {
        /**
         * Resolves a Backend-provided posting-mode token into a [PostingMode].
         *
         * Matching is case-insensitive and tolerant of surrounding whitespace.
         * `"forwarding"` and the composite `"both"` (campaign + forwarding) resolve
         * to [FORWARDING]; every other value — including `"campaign"`, `"none"`,
         * blank, or unrecognized — resolves to [CAMPAIGN], matching the Backend
         * default (`mode: str = MODE_CAMPAIGN`).
         */
        fun fromBackend(value: String?): PostingMode =
            when (value?.trim()?.lowercase()) {
                "forwarding", "both" -> FORWARDING
                else -> CAMPAIGN
            }
    }
}
