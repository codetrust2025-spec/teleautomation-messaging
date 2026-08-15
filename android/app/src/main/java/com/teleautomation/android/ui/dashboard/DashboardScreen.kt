package com.teleautomation.android.ui.dashboard

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.teleautomation.android.core.CycleCountdown
import com.teleautomation.android.data.api.DashboardFigures
import com.teleautomation.android.data.api.WorkspaceMode
import com.teleautomation.android.presentation.DashboardUiState
import com.teleautomation.android.presentation.DashboardViewModel
import com.teleautomation.android.ui.common.SuccessConfirmationHost
import com.teleautomation.android.ui.common.TransientStateHost
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Dashboard / fleet overview screen (R6).
 *
 * Stateless with respect to business logic: it observes [DashboardViewModel.uiState]
 * and forwards intents (mode selection, start/stop, reach reset, pull-to-refresh)
 * back to the ViewModel (MVVM). Composition of the figures themselves is delegated
 * to [TransientStateHost] so loading / error+retry / content all share the app-wide
 * transient-state treatment (R25), with the last figures retained behind an error
 * (R6.2).
 *
 * Wired into [com.teleautomation.android.ui.nav.NavScaffold] as the Admin Dashboard
 * destination. The fleet-control actions are gated on the Backend by the fleet-admin
 * dependency; a non-Admin would receive a `403` surfaced as an action error.
 *
 * @param modifier applied to the screen container.
 * @param inboxNewCount the inbox-new count combined into the summary. It comes from
 *   the Inbox module (`GET /inbox`, R11.1), not `/state`, so it is supplied here as
 *   a wired-in input and defaults to `0` until the inbox feed provides it.
 * @param viewModel the Hilt-provided [DashboardViewModel].
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    modifier: Modifier = Modifier,
    inboxNewCount: Int = 0,
    viewModel: DashboardViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    // Feed the externally supplied inbox-new count into the summary (R6.1).
    LaunchedEffect(inboxNewCount) { viewModel.setInboxNewCount(inboxNewCount) }

    DashboardContent(
        uiState = uiState,
        modifier = modifier,
        onModeSelected = viewModel::onModeSelected,
        onStartAll = viewModel::startAll,
        onStopAll = viewModel::stopAll,
        onRequestReachReset = viewModel::requestReachReset,
        onReachResetOutcome = viewModel::onReachResetOutcome,
        onRefresh = viewModel::refresh,
        onRetry = viewModel::retry,
        onDismissSuccess = viewModel::dismissSuccessMessage,
        onDismissActionError = viewModel::dismissActionError,
    )
}

/**
 * Stateless dashboard body, split out so it is previewable and testable without a
 * ViewModel. Renders the Workspace_Mode selector, the fleet-control actions, the
 * sleep countdown, and the figures, and hosts the reach-reset confirmation dialog.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DashboardContent(
    uiState: DashboardUiState,
    modifier: Modifier = Modifier,
    onModeSelected: (WorkspaceMode) -> Unit = {},
    onStartAll: () -> Unit = {},
    onStopAll: () -> Unit = {},
    onRequestReachReset: () -> Unit = {},
    onReachResetOutcome: (com.teleautomation.android.core.ConfirmationOutcome) -> Unit = {},
    onRefresh: () -> Unit = {},
    onRetry: () -> Unit = {},
    onDismissSuccess: () -> Unit = {},
    onDismissActionError: () -> Unit = {},
) {
    Column(modifier = modifier.fillMaxSize()) {
        SuccessConfirmationHost(
            message = uiState.successMessage,
            onDismiss = onDismissSuccess,
        )
        uiState.actionError?.let { error ->
            ActionErrorBanner(message = error, onDismiss = onDismissActionError)
        }

        WorkspaceModeSelector(
            selected = uiState.selectedMode,
            onSelected = onModeSelected,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        )

        FleetControls(
            isActionInFlight = uiState.isActionInFlight,
            onStartAll = onStartAll,
            onStopAll = onStopAll,
            onRequestReachReset = onRequestReachReset,
            modifier = Modifier.padding(horizontal = 16.dp),
        )

        uiState.countdown?.let { countdown ->
            SleepCountdown(
                countdown = countdown,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
        }

        PullToRefreshBox(
            isRefreshing = uiState.isRefreshing,
            onRefresh = onRefresh,
            modifier = Modifier.fillMaxSize(),
        ) {
            TransientStateHost(
                state = uiState.figures,
                onRetry = onRetry,
                emptyMessage = "No fleet data available.",
            ) { figures ->
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    FiguresGrid(figures = figures, inboxNewCount = uiState.inboxNewCount)
                }
            }
        }
    }

    if (uiState.showResetDialog) {
        com.teleautomation.android.ui.common.ConfirmDialog(
            title = "Reset reach?",
            message = "This clears the posts-sent and reach counters for the fleet. " +
                "This cannot be undone.",
            confirmLabel = "Reset",
            cancelLabel = "Cancel",
            onOutcome = onReachResetOutcome,
        )
    }
}

/**
 * The exactly-three-value Workspace_Mode selector (R6.3), rendered as a row of
 * single-choice filter chips. Selecting a mode re-filters every displayed figure.
 */
@Composable
private fun WorkspaceModeSelector(
    selected: WorkspaceMode,
    onSelected: (WorkspaceMode) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = "Workspace mode selector" },
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        WorkspaceMode.DASHBOARD_MODES.forEach { mode ->
            FilterChip(
                selected = mode == selected,
                onClick = { onSelected(mode) },
                label = { Text(mode.displayLabel()) },
                modifier = Modifier.semantics { contentDescription = "${mode.displayLabel()} mode" },
            )
        }
    }
}

/** Start-all / stop-all and reach-reset controls (R6.4, R6.5, R6.8). */
@Composable
private fun FleetControls(
    isActionInFlight: Boolean,
    onStartAll: () -> Unit,
    onStopAll: () -> Unit,
    onRequestReachReset: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Button(
            onClick = onStartAll,
            enabled = !isActionInFlight,
            modifier = Modifier
                .weight(1f)
                .semantics { contentDescription = "Start all accounts" },
        ) {
            Icon(
                imageVector = Icons.Filled.PlayArrow,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
            )
            Text(text = "Start all", modifier = Modifier.padding(start = 6.dp))
        }
        OutlinedButton(
            onClick = onStopAll,
            enabled = !isActionInFlight,
            modifier = Modifier
                .weight(1f)
                .semantics { contentDescription = "Stop all accounts" },
        ) {
            Icon(
                imageVector = Icons.Filled.Stop,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
            )
            Text(text = "Stop all", modifier = Modifier.padding(start = 6.dp))
        }
        OutlinedButton(
            onClick = onRequestReachReset,
            enabled = !isActionInFlight,
            modifier = Modifier.semantics { contentDescription = "Reset reach" },
        ) {
            Icon(
                imageVector = Icons.Filled.RestartAlt,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}

/** Per-second countdown to the next fleet cycle while accounts are sleeping (R6.7). */
@Composable
private fun SleepCountdown(
    countdown: CycleCountdown,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = "Next cycle in ${countdown.label}" },
        color = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text = "Sleeping — next cycle in", style = MaterialTheme.typography.bodyMedium)
            Text(
                text = countdown.label,
                style = MaterialTheme.typography.titleMedium,
            )
        }
    }
}

/** Renders all dashboard figures (R6.1) as a set of labeled stat cards. */
@Composable
private fun FiguresGrid(
    figures: DashboardFigures,
    inboxNewCount: Int,
) {
    val cells = listOf(
        "Accounts" to figures.accountCount.toString(),
        "Running" to figures.runningCount.toString(),
        "Resting" to figures.restingCount.toString(),
        "Posts sent" to figures.postsSent.toString(),
        "Inbox new" to inboxNewCount.toString(),
        "Success rate" to "${figures.successRatePct}%",
    )
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        cells.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                row.forEach { (label, value) ->
                    StatCard(
                        label = label,
                        value = value,
                        modifier = Modifier.weight(1f),
                    )
                }
                if (row.size == 1) {
                    Box(modifier = Modifier.weight(1f))
                }
            }
        }
    }
}

/** A single labeled figure card. */
@Composable
private fun StatCard(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.semantics { contentDescription = "$label: $value" },
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(text = value, style = MaterialTheme.typography.headlineSmall)
            Text(text = label, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

/**
 * Compact, dismissible error banner for a failed start/stop/reset action (R6.6).
 * The displayed figures are left unchanged; only this banner surfaces the failure.
 */
@Composable
private fun ActionErrorBanner(
    message: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = "Action error: $message" },
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = message,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
            )
            OutlinedButton(onClick = onDismiss) { Text("Dismiss") }
        }
    }
}

/** Human-readable label for a [WorkspaceMode] chip (R6.3). */
private fun WorkspaceMode.displayLabel(): String = when (this) {
    WorkspaceMode.FLEET -> "Fleet"
    WorkspaceMode.FORWARDING -> "Forwarding"
    WorkspaceMode.CAMPAIGN -> "Campaign"
}

@Preview(showBackground = true)
@Composable
private fun DashboardContentPreview() {
    TeleAutomationTheme {
        DashboardContent(
            uiState = DashboardUiState(
                figures = com.teleautomation.android.core.ViewState.Content(
                    DashboardFigures(
                        accountCount = 6,
                        runningCount = 4,
                        restingCount = 2,
                        postsSent = 128,
                        postsAttempted = 140,
                        successRatePct = 91,
                        nextCycleRemainingMillis = 5_400_000L,
                    ),
                ),
                inboxNewCount = 3,
                countdown = com.teleautomation.android.core.CycleCountdownFormatter
                    .formatClamped(5_400_000L),
            ),
        )
    }
}
