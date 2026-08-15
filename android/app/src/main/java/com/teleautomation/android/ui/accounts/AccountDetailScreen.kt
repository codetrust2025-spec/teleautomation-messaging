package com.teleautomation.android.ui.accounts

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.teleautomation.android.core.DisplayNameValidator
import com.teleautomation.android.data.api.AccountSlot
import com.teleautomation.android.data.api.PostingMode
import com.teleautomation.android.presentation.AccountsUiState
import com.teleautomation.android.ui.common.SuccessConfirmationHost
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Single-account detail screen (R7.3–R7.8): start/stop, edit display name, change
 * posting mode, refresh joined-group count, and a navigation hook to the Telegram
 * OTP login screen (R8, built in task 10.6).
 *
 * Stateless with respect to business logic — it renders the [account] row and the
 * shared [uiState] and forwards intents to the [AccountsViewModel] via callbacks.
 * The display-name field validates `[1,64]` locally via [DisplayNameValidator] to
 * disable the save action for an invalid length (the ViewModel re-validates before
 * any network call, R7.6).
 *
 * @param account the account row being detailed (assembled composite, R7.1).
 * @param uiState the shared Accounts UI state (busy/error/success indications).
 * @param onBack returns to the list.
 * @param onStart / onStop per-account start/stop (R7.3).
 * @param onRename submits a validated display name (R7.5).
 * @param onChangePostingMode submits a new posting mode (R7.7).
 * @param onRefreshJoined rescans the joined-group count (R7.8).
 * @param onLoginTelegram the navigation hook to the OTP login screen for this slot
 *   (R8 / task 10.6); this task wires the hook only.
 * @param onDismissSlotError clears this slot's error indication.
 * @param onDismissSuccess clears the success confirmation.
 */
@Composable
fun AccountDetailScreen(
    account: AccountSlot,
    uiState: AccountsUiState,
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onStart: (String) -> Unit = {},
    onStop: (String) -> Unit = {},
    onRename: (String, String) -> Unit = { _, _ -> },
    onChangePostingMode: (String, PostingMode) -> Unit = { _, _ -> },
    onRefreshJoined: (String) -> Unit = {},
    onLoginTelegram: (String) -> Unit = {},
    onDismissSlotError: (String) -> Unit = {},
    onDismissSuccess: () -> Unit = {},
) {
    val busy = account.slot in uiState.busySlots
    val error = uiState.slotErrors[account.slot]

    var nameDraft by remember(account.slot, account.displayName) {
        mutableStateOf(account.displayName)
    }
    val nameValid = DisplayNameValidator.validate(nameDraft) is
        com.teleautomation.android.core.BoundedLengthResult.Accepted

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        SuccessConfirmationHost(message = uiState.successMessage, onDismiss = onDismissSuccess)

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = onBack,
                modifier = Modifier.semantics { contentDescription = "Back to accounts" },
            ) {
                Icon(imageVector = Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null)
            }
            Text(text = account.displayName, style = MaterialTheme.typography.titleLarge)
        }

        Column(
            modifier = Modifier.padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // Status + joined-group count summary (R7.1, R7.8).
            Surface(
                color = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(text = "Slot: ${account.slot}", style = MaterialTheme.typography.bodyMedium)
                    Text(
                        text = "Status: ${statusLabel(account.status)}",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.semantics {
                            contentDescription = "Status ${statusLabel(account.status)}"
                        },
                    )
                    Text(
                        text = "Joined groups: ${account.joinedGroupCount}",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

            error?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            // Start / stop (R7.3, R7.4).
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Button(
                    onClick = { onStart(account.slot) },
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
                    onClick = { onStop(account.slot) },
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

            HorizontalDivider()

            // Display name edit (R7.5, R7.6).
            Text(text = "Display name", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = nameDraft,
                onValueChange = {
                    nameDraft = it
                    if (error != null) onDismissSlotError(account.slot)
                },
                singleLine = true,
                label = { Text("Name (1–${DisplayNameValidator.MAX_LENGTH})") },
                isError = !nameValid,
                supportingText = {
                    if (!nameValid) {
                        Text("Name must be 1 to ${DisplayNameValidator.MAX_LENGTH} characters.")
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = "Display name field" },
            )
            Button(
                onClick = { onRename(account.slot, nameDraft) },
                enabled = !busy && nameValid && nameDraft.trim() != account.displayName,
                modifier = Modifier.semantics { contentDescription = "Save display name" },
            ) {
                Text("Save name")
            }

            HorizontalDivider()

            // Posting mode (R7.7).
            Text(text = "Posting mode", style = MaterialTheme.typography.titleMedium)
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = "Posting mode selector" },
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                listOf(PostingMode.CAMPAIGN, PostingMode.FORWARDING).forEach { mode ->
                    FilterChip(
                        selected = mode == account.postingMode,
                        onClick = { if (mode != account.postingMode) onChangePostingMode(account.slot, mode) },
                        enabled = !busy,
                        label = { Text(postingModeLabel(mode)) },
                        modifier = Modifier.semantics {
                            contentDescription = "${postingModeLabel(mode)} mode"
                        },
                    )
                }
            }

            HorizontalDivider()

            // Refresh joined-group count (R7.8).
            OutlinedButton(
                onClick = { onRefreshJoined(account.slot) },
                enabled = !busy,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = "Refresh joined groups" },
            ) {
                Icon(
                    imageVector = Icons.Filled.Refresh,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Text(text = "Refresh joined groups", modifier = Modifier.padding(start = 8.dp))
            }

            HorizontalDivider()

            // Telegram OTP login navigation hook (R8 / task 10.6).
            Button(
                onClick = { onLoginTelegram(account.slot) },
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = "Log in Telegram for ${account.slot}" },
            ) {
                Text("Log in Telegram account")
            }

            // Trailing spacer so the last control clears the bottom inset.
            Text(text = "", modifier = Modifier.padding(bottom = 8.dp))
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun AccountDetailPreview() {
    TeleAutomationTheme {
        AccountDetailScreen(
            account = AccountSlot("account1", "Sales A", "running", 42, PostingMode.CAMPAIGN),
            uiState = AccountsUiState(),
        )
    }
}
