package com.teleautomation.android.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Operator role mirrored from the Backend `/auth/status` `role` field.
 *
 * The Backend reports the role as a lowercase string (`"admin"` / `"handler"`).
 * Defined once here in `data.api` because both the auth DTOs and the
 * role-based navigation/scoping logic consume it (R4).
 *
 * Per the Web_App reference, an absent or unrecognized role defaults to
 * [ADMIN]; see [fromBackend].
 */
@Serializable
enum class Role {
    @SerialName("admin")
    ADMIN,

    @SerialName("handler")
    HANDLER,
    ;

    companion object {
        /**
         * Resolves a Backend-provided role token into a [Role].
         *
         * Matching is case-insensitive and tolerant of surrounding whitespace.
         * A `null`, blank, or unrecognized value resolves to [ADMIN], matching
         * the Web_App default when the field is absent.
         */
        fun fromBackend(value: String?): Role =
            when (value?.trim()?.lowercase()) {
                "handler" -> HANDLER
                "admin" -> ADMIN
                else -> ADMIN
            }
    }
}
