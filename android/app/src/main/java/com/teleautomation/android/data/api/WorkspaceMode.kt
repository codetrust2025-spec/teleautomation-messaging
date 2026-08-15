package com.teleautomation.android.data.api

/**
 * The dashboard scope selector (R6.3).
 *
 * Mirrors the Web_App `Workspace_Mode` (see `dashboard/src/utils/workspaceDashboard.js`):
 * the dashboard can show the whole [FLEET], or narrow the displayed figures to only
 * the accounts/metrics associated with the [FORWARDING] or [CAMPAIGN] posting mode.
 *
 * This is a pure client-side selector — it is not sent to the Backend; it only
 * filters which per-account figures from `GET /state` are aggregated for display
 * (the DashboardScreen in task 9.7 uses it). [DASHBOARD_MODES] enumerates exactly
 * the three values required by R6.3.
 */
enum class WorkspaceMode {
    /** Show all logged-in accounts and combined figures. */
    FLEET,

    /** Show only accounts/metrics operating in forwarding mode. */
    FORWARDING,

    /** Show only accounts/metrics operating in campaign mode. */
    CAMPAIGN,
    ;

    companion object {
        /** The exact set of selectable workspace modes required by R6.3, in display order. */
        val DASHBOARD_MODES: List<WorkspaceMode> = listOf(FLEET, FORWARDING, CAMPAIGN)
    }
}
