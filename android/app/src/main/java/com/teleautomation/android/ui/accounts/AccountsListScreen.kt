package com.teleautomation.android.ui.accounts

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.teleautomation.android.data.api.AccountSlot
import com.teleautomation.android.data.api.PostingMode
import com.teleautomation.android.data.api.ShutdownEntry
import com.teleautomation.android.presentation.AccountsUiState
import com.teleautomation.android.presentation.AccountsViewModel
import com.teleautomation.android.ui.common.SuccessConfirmationHost
import com.teleautomation.android.ui.common.TransientStateHost
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Accounts module entry point wired into
 * [com.teleautomation.android.ui.nav.NavScaffold] in place of the placeholder (R7).
 *
 * Hosts a single shared [AccountsViewModel] (so list and detail observe the same
 * state) and switches between the stacked-card list and a single-account detail view
 * using a saved selected-slot. Selecting an account opens its detail; the detail's
 * back action returns to the list. The detail exposes [onLoginTelegram] — the
 * navigation hook to the Telegram OTP login screen (built in task 10.6) — which is
 * surfaced here as a callback so this task wires only the hook, not that screen.
 *
 * @param onLoginTelegram invoked with the target slot when the Operator chooses to
 *   log a Telegram account into it; the host routes to the OTP login screen (10.6).
 * @param modifier applied to the route container.
 * @param viewModel the Hilt-provided [AccountsViewModel] shared by both views.
 */
@Composable
fun AccountsRoute(
    onLoginTelegram: (String) -> Unit = {},
    modifier: Modifier = Modifier,
    viewModel: AccountsViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var selectedSlot by androidx.compose.runtime.saveable.rememberSaveable {
        androidx.compose.runtime.mutableStateOf<String?>(null)
    }

    val accountsContent = (uiState.accounts as? com.teleautomation.android.core.ViewState.Content)?.data
    val selectedAccount = accountsContent?.firstOrNull { it.slot == selectedSlot }

    // Recover from a stale selection (slot removed from the list while detailed)
    // without writing state during composition.
    androidx.compose.runtime.LaunchedEffect(selectedSlot, accountsContent) {
        if (selectedSlot != null && accountsContent != null && selectedAccount == null) {
            selectedSlot = null
        }
    }

    if (selectedSlot != null && selectedAccount != null) {
        AccountDetailScreen(
            account = selectedAccount,
            uiState = uiState,
            modifier = modifier,
            onBack = { selectedSlot = null },
            onStart = { viewModel.startAccount(it) },
            onStop = { viewModel.stopAccount(it) },
            onRename = { slot, name -> viewModel.editDisplayName(slot, name) },
            onChangePostingMode = { slot, mode -> viewModel.changePostingMode(slot, mode) },
            onRefreshJoined = { viewModel.refreshJoined(it) },
            onLoginTelegram = onLoginTelegram,
            onDismissSlotError = { viewModel.dismissSlotError(it) },
            onDismissSuccess = viewModel::dismissSuccessMessage,
        )
    } else {
        AccountsListScreen(
            uiState = uiState,
            modifier = modifier,
            onOpenDetail = { selectedSlot = it },
            onStart = { viewModel.startAccount(it) },
            onStop = { viewModel.stopAccount(it) },
            onProvision = viewModel::provisionSlot,
            onClearShutdown = { viewModel.clearShutdown(it) },
            onRetry = viewModel::retry,
            onDismissProvisionError = viewModel::dismissProvisionError,
            onDismissActionError = viewModel::dismissActionError,
            onDismissSuccess = viewModel::dismissSuccessMessage,
        )
    }
}

/**
 * Stateless Accounts list: stacked cards (display name, status, joined-group count,
 * posting mode) with per-account start/stop, a shutdown-list section, and a
 * provision-slot action (R7.1, R7.3, R7.9, R7.11, R24.1).
 *
 * The roster itself is rendered through [TransientStateHost] so loading / empty /
 * error+retry share the app-wide transient-state treatment, retaining the last list
 * behind a load error (R7.2, R25).
 */
@Composable
fun AccountsListScreen(
    uiState: AccountsUiState,
    modifier: Modifier = Modifier,
    onOpenDetail: (String) -> Unit = {},
    onStart: (String) -> Unit = {},
    onStop: (String) -> Unit = {},
    onProvision: () -> Unit = {},
    onClearShutdown: (String) -> Unit = {},
    onRetry: () -> Unit = {},
    onDismissProvisionError: () -> Unit = {},
    onDismissActionError: () -> Unit = {},
    onDismissSuccess: () -> Unit = {},
) {
    Column(modifier = modifier.fillMaxSize()) {
        SuccessConfirmationHost(message = uiState.successMessage, onDismiss = onDismissSuccess)
        uiState.actionError?.let { error ->
            DismissibleBanner(message = error, onDismiss = onDismissActionError)
        }
        uiState.provisionError?.let { error ->
            DismissibleBanner(message = error, onDismiss = onDismissProvisionError)
        }

        TransientStateHost(
            state = uiState.accounts,
            onRetry = onRetry,
            emptyMessage = "No accounts configured.",
            modifier = Modifier.fillMaxSize(),
        ) { accounts ->
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (uiState.shutdownEntries.isNotEmpty()) {
                    item {
                        Text(
                            text = "Shutdown list",
                            style = MaterialTheme.typography.titleMedium,
                        )
                    }
                    items(uiState.shutdownEntries, key = { "shutdown-${it.slot}" }) { entry ->
                        ShutdownCard(entry = entry, onClear = { onClearShutdown(entry.slot) })
                    }
                    item { HorizontalDivider() }
                }

                items(accounts, key = { it.slot }) { account ->
                    AccountCard(
                        account = account,
                        busy = account.slot in uiState.busySlots,
                        error = uiState.slotErrors[account.slot],
                        onOpen = { onOpenDetail(account.slot) },
                        onStart = { onStart(account.slot) },
                        onStop = { onStop(account.slot) },
                    )
                }

                item {
                    Button(
                        onClick = onProvision,
                        enabled = !uiState.isProvisioning,
                        modifier = Modifier
                            .fillMaxWidth()
                            .semantics { contentDescription = "Provision new account slot" },
                    ) {
                        if (uiState.isProvisioning) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(18.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Filled.Add,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp),
                            )
                        }
                        Text(text = "Provision new slot", modifier = Modifier.padding(start = 8.dp))
                    }
                }
            }
        }
    }
}

/** A single stacked account card (R24.1): name, status, joined count, mode, controls. */
@Composable
private fun AccountCard(
    account: AccountSlot,
    busy: Boolean,
    error: String?,
    onOpen: () -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen)
            .semantics { contentDescription = "Account ${account.displayName}" },
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = account.displayName,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = account.slot,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Icon(imageVector = Icons.Filled.ChevronRight, contentDescription = null)
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(
                    onClick = {},
                    enabled = false,
                    label = { Text(statusLabel(account.status)) },
                )
                AssistChip(
                    onClick = {},
                    enabled = false,
                    label = { Text(postingModeLabel(account.postingMode)) },
                )
            }

            Text(
                text = "Joined groups: ${account.joinedGroupCount}",
                style = MaterialTheme.typography.bodyMedium,
            )

            error?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Button(
                    onClick = onStart,
                    enabled = !busy,
                    modifier = Modifier
                        .weight(1f)
                        .semantics { contentDescription = "Start ${account.slot}" },
                ) {
                    Icon(
                        imageVector = Icons.Filled.PlayArrow,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(text = "Start", modifier = Modifier.padding(start = 6.dp))
                }
                OutlinedButton(
                    onClick = onStop,
                    enabled = !busy,
                    modifier = Modifier
                        .weight(1f)
                        .semantics { contentDescription = "Stop ${account.slot}" },
                ) {
                    Icon(
                        imageVector = Icons.Filled.Stop,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(text = "Stop", modifier = Modifier.padding(start = 6.dp))
                }
                if (busy) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                }
            }
        }
    }
}

/** A shutdown-list entry card with a clear action (R7.11, R7.12). */
@Composable
private fun ShutdownCard(
    entry: ShutdownEntry,
    onClear: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = "Shutdown entry ${entry.slot}" },
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = entry.slot, style = MaterialTheme.typography.titleSmall)
                Text(
                    text = entry.reason.ifBlank { "Auto-shutdown" },
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            OutlinedButton(
                onClick = onClear,
                modifier = Modifier.semantics { contentDescription = "Clear shutdown ${entry.slot}" },
            ) {
                Text("Clear")
            }
        }
    }
}

/** Compact dismissible error banner. */
@Composable
private fun DismissibleBanner(
    message: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = "Error: $message" },
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text = message, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = onDismiss) { Text("Dismiss") }
        }
    }
}

/** Human-readable account status, falling back to "Unknown" for a blank token. */
internal fun statusLabel(status: String): String =
    status.takeIf { it.isNotBlank() }?.replaceFirstChar { it.uppercase() } ?: "Unknown"

/** Human-readable posting-mode label (R7.7). */
internal fun postingModeLabel(mode: PostingMode): String = when (mode) {
    PostingMode.FORWARDING -> "Forwarding"
    PostingMode.CAMPAIGN -> "Campaign"
}

@Preview(showBackground = true)
@Composable
private fun AccountsListPreview() {
    TeleAutomationTheme {
        AccountsListScreen(
            uiState = AccountsUiState(
                accounts = com.teleautomation.android.core.ViewState.Content(
                    listOf(
                        AccountSlot("account1", "Sales A", "running", 42, PostingMode.CAMPAIGN),
                        AccountSlot("account2", "Sales B", "stopped", 0, PostingMode.FORWARDING),
                    ),
                ),
                shutdownEntries = listOf(ShutdownEntry(slot = "account3", reason = "no_post_6h")),
            ),
        )
    }
}
