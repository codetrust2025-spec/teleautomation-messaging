package com.teleautomation.android.ui.components

import com.teleautomation.android.core.realtime.ConnectionState
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.nulls.shouldNotBeNull
import io.kotest.matchers.shouldBe

/**
 * Example-based unit tests for the pure offline-indicator decision (R22.7).
 *
 * The banner is shown for every [ConnectionState] except [ConnectionState.Connected]
 * (which yields no message). This isolates the show/hide rule and copy from the
 * Compose rendering so it is verifiable without a device.
 */
class OfflineBannerLogicTest : StringSpec({

    "connected yields no banner message" {
        offlineMessageFor(ConnectionState.Connected) shouldBe null
    }

    "every non-connected state yields a banner message (R22.7)" {
        ConnectionState.entries
            .filter { it != ConnectionState.Connected }
            .forEach { state ->
                offlineMessageFor(state).shouldNotBeNull()
            }
    }

    "isConnected is true only for Connected" {
        ConnectionState.entries.forEach { state ->
            state.isConnected shouldBe (state == ConnectionState.Connected)
        }
    }
})
