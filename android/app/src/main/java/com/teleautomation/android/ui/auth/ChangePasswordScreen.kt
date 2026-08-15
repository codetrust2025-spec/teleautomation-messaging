package com.teleautomation.android.ui.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.teleautomation.android.presentation.ChangePasswordUiState
import com.teleautomation.android.presentation.ChangePasswordViewModel
import com.teleautomation.android.ui.common.SuccessConfirmationHost
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Authenticated change-password screen, reached from the settings/profile area
 * (R3.5).
 *
 * Stateful entry point: obtains [ChangePasswordViewModel] from Hilt, observes its
 * [ChangePasswordViewModel.uiState], and delegates rendering to the stateless
 * [ChangePasswordContent]. All validation/persistence lives in the
 * ViewModel/repository; this composable only renders state and forwards intents
 * (MVVM).
 *
 * @param onNavigateBack invoked when the Operator dismisses the screen (e.g. the
 *   top-bar back control), returning to the previous screen.
 */
@Composable
fun ChangePasswordScreen(
    onNavigateBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ChangePasswordViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    ChangePasswordContent(
        state = uiState,
        onCurrentPasswordChanged = viewModel::onCurrentPasswordChanged,
        onNewPasswordChanged = viewModel::onNewPasswordChanged,
        onSubmit = viewModel::onSubmit,
        onSuccessConfirmationDismissed = viewModel::onSuccessConfirmationDismissed,
        onNavigateBack = onNavigateBack,
        modifier = modifier,
    )
}

/**
 * Stateless rendering of the change-password form. Kept separate from
 * [ChangePasswordScreen] so it can be previewed and tested without Hilt.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChangePasswordContent(
    state: ChangePasswordUiState,
    onCurrentPasswordChanged: (String) -> Unit,
    onNewPasswordChanged: (String) -> Unit,
    onSubmit: () -> Unit,
    onSuccessConfirmationDismissed: () -> Unit,
    onNavigateBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var currentVisible by rememberSaveable { mutableStateOf(false) }
    var newVisible by rememberSaveable { mutableStateOf(false) }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text("Change password") },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                        )
                    }
                },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .imePadding()
                .padding(horizontal = 16.dp, vertical = 16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // Success confirmation stays visible for the minimum window (R3.6, R25.3).
            SuccessConfirmationHost(
                message = state.successMessage,
                onDismiss = onSuccessConfirmationDismissed,
            )

            Text(
                text = "Enter your current password and a new password between 8 and " +
                    "128 characters.",
                style = MaterialTheme.typography.bodyMedium,
            )

            OutlinedTextField(
                value = state.currentPassword,
                onValueChange = onCurrentPasswordChanged,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Current password") },
                singleLine = true,
                isError = state.currentPasswordError != null,
                enabled = !state.isSubmitting,
                visualTransformation = if (currentVisible) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    imeAction = ImeAction.Next,
                ),
                trailingIcon = {
                    PasswordVisibilityToggle(
                        visible = currentVisible,
                        onToggle = { currentVisible = !currentVisible },
                    )
                },
                supportingText = state.currentPasswordError?.let { { ErrorText(it) } },
            )

            OutlinedTextField(
                value = state.newPassword,
                onValueChange = onNewPasswordChanged,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("New password") },
                singleLine = true,
                isError = state.newPasswordError != null,
                enabled = !state.isSubmitting,
                visualTransformation = if (newVisible) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    imeAction = ImeAction.Done,
                ),
                trailingIcon = {
                    PasswordVisibilityToggle(
                        visible = newVisible,
                        onToggle = { newVisible = !newVisible },
                    )
                },
                supportingText = state.newPasswordError?.let { { ErrorText(it) } },
            )

            if (state.errorMessage != null) {
                Text(
                    text = state.errorMessage,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            Button(
                onClick = onSubmit,
                enabled = !state.isSubmitting,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isSubmitting) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else {
                    Text("Change password")
                }
            }
        }
    }
}

@Composable
private fun ErrorText(message: String) {
    Text(text = message, color = MaterialTheme.colorScheme.error)
}

@Composable
private fun PasswordVisibilityToggle(visible: Boolean, onToggle: () -> Unit) {
    IconButton(onClick = onToggle) {
        Icon(
            imageVector = if (visible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
            contentDescription = if (visible) "Hide password" else "Show password",
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun ChangePasswordContentPreview() {
    TeleAutomationTheme {
        ChangePasswordContent(
            state = ChangePasswordUiState(
                currentPassword = "current-pass",
                newPassword = "new-secret-pass",
            ),
            onCurrentPasswordChanged = {},
            onNewPasswordChanged = {},
            onSubmit = {},
            onSuccessConfirmationDismissed = {},
            onNavigateBack = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun ChangePasswordContentErrorPreview() {
    TeleAutomationTheme {
        ChangePasswordContent(
            state = ChangePasswordUiState(
                currentPassword = "current-pass",
                newPassword = "short",
                newPasswordError = "Must be at least 8 characters (was 5).",
                errorMessage = "Your current password is incorrect.",
            ),
            onCurrentPasswordChanged = {},
            onNewPasswordChanged = {},
            onSubmit = {},
            onSuccessConfirmationDismissed = {},
            onNavigateBack = {},
        )
    }
}
