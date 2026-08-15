/**
 * `ui.common` — reusable, cross-feature Compose building blocks.
 *
 * Holds the transient-state scaffolding shared by every data-backed screen:
 * [com.teleautomation.android.ui.common.TransientStateHost] (renders
 * loading / empty / content / error+retry from a
 * [com.teleautomation.android.core.ViewState], R25.1–R25.5) and
 * [com.teleautomation.android.ui.common.SuccessConfirmationHost] (a success
 * confirmation that stays visible for at least 3 seconds or until dismissed,
 * R25.3).
 *
 * These composables render state only; the selection logic lives in
 * [com.teleautomation.android.core.ViewStateSelector] so it stays JVM-testable.
 */
package com.teleautomation.android.ui.common
