package com.teleautomation.android.data.local

/**
 * The runtime-configurable Backend connection configuration (R23.6).
 *
 * Currently holds only the validated Backend base [baseUrl]. The value stored in a
 * [BackendConfig] has already passed
 * [com.teleautomation.android.core.BackendUrlPolicy.validate]; it is a
 * syntactically valid URL using the `http`, `https`, `ws`, or `wss` scheme with a
 * non-empty host. Persisted via DataStore Preferences by
 * [com.teleautomation.android.data.repo.BackendConfigRepository].
 */
data class BackendConfig(
    val baseUrl: String,
)
