/**
 * `ui.accounts` — Compose screens for account/fleet management (R7).
 *
 * Hosts the `AccountsRoute` entry point (wired into `NavScaffold` for the Accounts
 * module), which presents the stacked-card `AccountsListScreen` and the
 * `AccountDetailScreen` over a shared `AccountsViewModel`. The list assembles
 * composite `AccountSlot` rows from `GET /accounts` merged with the `GET /state`
 * worker map and renders per-account start/stop, the shutdown list, and slot
 * provisioning; the detail view handles display-name edit, posting-mode change,
 * refresh-joined, and exposes the navigation hook to the Telegram OTP login screen
 * (R8 / task 10.6). Screens observe immutable state from the ViewModel and contain
 * no business logic.
 */
package com.teleautomation.android.ui.accounts
