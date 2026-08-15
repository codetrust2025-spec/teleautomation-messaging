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
import androidx.compose.runtime.remember
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
import com.teleautomation.android.presentation.ForgotPasswordUiState
import com.teleautomation.android.presentation.ForgotPasswordViewModel
import com.teleautomation.android.ui.common.SuccessConfirmationHost
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Self-service password reset screen, reached from the login screen's
 * "Forgot password" entry point (R3.1).
 *
 * Stateful entry point: obtains [ForgotPasswordViewModel] from Hilt, observes its
 * [ForgotPasswordViewModel.uiState], and delegates rendering to the stateless
 * [ForgotPasswordContent]. All validation/persistence lives in the
 * ViewModel/repository; this composable only renders state and forwards intents
 * (MVVM).
 *
 * @param onNavigateBack invoked when the Operator dismisses the flow (e.g. the
 *   top-bar back control), returning to the login screen.
 */
@Composable
fun ForgotPasswordScreen(
    onNavigateBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ForgotPasswordViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    ForgotPasswordContent(
        state = uiState,
        onUsernameChanged = viewModel::onUsernameChanged,
        onReferenceChanged = viewModel::onReferenceChanged,
        onNewPasswordChanged = viewModel::onNewPasswordChanged,
        onSubmit = viewModel::onSubmit,
        onSuccessConfirmationDismissed = viewModel::onSuccessConfirmationDismissed,
        onNavigateBack = onNavigateBack,
        modifier = modifier,
    )
}

/**
 * Stateless rendering of the reset flow. Kept separate from [ForgotPasswordScreen]
 * so it can be previewed and tested without Hilt.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ForgotPasswordContent(
    state: ForgotPasswordUiState,
    onUsernameChanged: (String) -> Unit,
    onReferenceChanged: (String) -> Unit,
    onNewPasswordChanged: (String) -> Unit,
    onSubmit: () -> Unit,
    onSuccessConfirmationDismissed: () -> Unit,
    onNavigateBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var passwordVisible by rememberSaveable { mutableStateOf(false) }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text("Reset password") },
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
            // Success confirmation stays visible for the minimum window (R3.3, R25.3).
            SuccessConfirmationHost(
                message = state.successMessage,
                onDismiss = onSuccessConfirmationDismissed,
            )

            Text(
                text = "Enter your username, reference, and a new password to reset " +
                    "your access.",
                style = MaterialTheme.typography.bodyMedium,
            )

            OutlinedTextField(
                value = state.username,
                onValueChange = onUsernameChanged,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Username") },
                singleLine = true,
                isError = state.usernameError != null,
                enabled = !state.isSubmitting,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                supportingText = state.usernameError?.let { { ErrorText(it) } },
            )

            OutlinedTextField(
                value = state.reference,
                onValueChange = onReferenceChanged,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Reference") },
                singleLine = true,
                isError = state.referenceError != null,
                enabled = !state.isSubmitting,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                supportingText = state.referenceError?.let { { ErrorText(it) } },
            )

            OutlinedTextField(
                value = state.newPassword,
                onValueChange = onNewPasswordChanged,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("New password") },
                singleLine = true,
                isError = state.newPasswordError != null,
                enabled = !state.isSubmitting,
                visualTransformation = if (passwordVisible) {
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
                        visible = passwordVisible,
                        onToggle = { passwordVisible = !passwordVisible },
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
                    Text("Reset password")
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
private fun ForgotPasswordContentPreview() {
    TeleAutomationTheme {
        ForgotPasswordContent(
            state = ForgotPasswordUiState(
                username = "handler1",
                reference = "REF-204",
                newPassword = "secret-pass",
            ),
            onUsernameChanged = {},
            onReferenceChanged = {},
            onNewPasswordChanged = {},
            onSubmit = {},
            onSuccessConfirmationDismissed = {},
            onNavigateBack = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun ForgotPasswordContentErrorPreview() {
    TeleAutomationTheme {
        ForgotPasswordContent(
            state = ForgotPasswordUiState(
                username = "handler1",
                reference = "REF-204",
                newPassword = "short",
                newPasswordError = "Must be at least 8 characters (was 5).",
                errorMessage = "The reference did not match our records.",
            ),
            onUsernameChanged = {},
            onReferenceChanged = {},
            onNewPasswordChanged = {},
            onSubmit = {},
            onSuccessConfirmationDismissed = {},
            onNavigateBack = {},
        )
    }
}
