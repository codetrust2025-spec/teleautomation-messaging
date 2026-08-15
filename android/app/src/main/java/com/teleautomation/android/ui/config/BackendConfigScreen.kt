package com.teleautomation.android.ui.config

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.teleautomation.android.presentation.BackendConfigUiState
import com.teleautomation.android.presentation.BackendConfigViewModel
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Screen that lets the Operator view, edit, and persist the Backend base URL
 * (R23.6).
 *
 * This is the stateful entry point: it obtains the [BackendConfigViewModel] from
 * Hilt, observes its [BackendConfigViewModel.uiState], and delegates rendering to
 * the stateless [BackendConfigContent]. All business logic (validation,
 * persistence) lives in the ViewModel/repository; this composable only renders
 * state and forwards user intents (MVVM).
 */
@Composable
fun BackendConfigScreen(
    modifier: Modifier = Modifier,
    viewModel: BackendConfigViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    BackendConfigContent(
        state = uiState,
        onInputChanged = viewModel::onInputChanged,
        onSave = viewModel::onSave,
        modifier = modifier,
    )
}

/**
 * Stateless rendering of the Backend configuration UI. Kept separate from
 * [BackendConfigScreen] so it can be previewed and (later) tested without Hilt.
 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun BackendConfigContent(
    state: BackendConfigUiState,
    onInputChanged: (String) -> Unit,
    onSave: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = { TopAppBar(title = { Text("Backend configuration") }) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp, vertical = 16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = "Set the Backend base URL the app connects to. " +
                    "Use an http, https, ws, or wss URL with a host, e.g. " +
                    "https://api.example.com.",
                style = MaterialTheme.typography.bodyMedium,
            )

            CurrentUrlRow(persistedUrl = state.persistedUrl)

            val isError = state.errorMessage != null
            OutlinedTextField(
                value = state.input,
                onValueChange = onInputChanged,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Backend base URL") },
                singleLine = true,
                isError = isError,
                enabled = !state.isSaving,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Done,
                ),
                supportingText = {
                    when {
                        isError -> Text(
                            text = state.errorMessage.orEmpty(),
                            color = MaterialTheme.colorScheme.error,
                        )

                        state.successMessage != null -> Text(text = state.successMessage)
                    }
                },
            )

            Button(
                onClick = onSave,
                enabled = !state.isSaving && state.input.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isSaving) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else {
                    Text("Save")
                }
            }

            if (state.successMessage != null) {
                SuccessConfirmation(message = state.successMessage)
            }
        }
    }
}

@Composable
private fun CurrentUrlRow(persistedUrl: String?) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(
            text = "Current Backend URL",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = persistedUrl ?: "Not configured",
            style = MaterialTheme.typography.bodyLarge,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun SuccessConfirmation(message: String) {
    androidx.compose.foundation.layout.Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(
            imageVector = Icons.Filled.CheckCircle,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.primary,
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun BackendConfigContentPreview() {
    TeleAutomationTheme {
        BackendConfigContent(
            state = BackendConfigUiState(
                persistedUrl = "https://api.example.com",
                input = "https://api.example.com",
            ),
            onInputChanged = {},
            onSave = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun BackendConfigContentErrorPreview() {
    TeleAutomationTheme {
        BackendConfigContent(
            state = BackendConfigUiState(
                persistedUrl = null,
                input = "ftp://nope",
                errorMessage = "Unsupported URL scheme \"ftp\"; expected one of http/https/ws/wss.",
            ),
            onInputChanged = {},
            onSave = {},
        )
    }
}
