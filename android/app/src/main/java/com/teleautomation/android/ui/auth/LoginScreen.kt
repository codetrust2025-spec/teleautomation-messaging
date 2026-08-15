package com.teleautomation.android.ui.auth

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
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.teleautomation.android.presentation.AuthViewModel
import com.teleautomation.android.presentation.LoginFormState
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Stateful operator login screen (R1.7–R1.11, R2.7), driven by [AuthViewModel].
 *
 * This is the thin stateful entry point in the auth-gate: it observes the
 * ViewModel's [AuthViewModel.loginForm] and forwards user intents, delegating all
 * rendering and the locally-held field text to the stateless [LoginContent] so the
 * pure presentation can be previewed/tested without Hilt (MVVM).
 *
 * The [gateErrorMessage]/[onRetry] inputs come from the auth-gate's
 * `AuthUiState.Unauthenticated(errorMessage)` branch: when the startup auth-status
 * check fails or times out (R1.4, R2.3) the screen also surfaces that gate error
 * with a retry control that re-runs the gate.
 *
 * @param viewModel the shared [AuthViewModel] owning the login form + auth gate.
 * @param onForgotPassword navigation hook to the self-service reset flow built in
 *   task 6.8 (R3.1); invoked when the "Forgot password" control is tapped.
 * @param gateErrorMessage the auth-gate error to show alongside the form, or `null`
 *   when login is shown for the ordinary "not signed in" reason (R1.2).
 * @param onRetry re-runs the startup auth-status check; shown only when
 *   [gateErrorMessage] is non-null (R2.3).
 * @param modifier applied to the screen container.
 */
@Composable
fun LoginScreen(
    viewModel: AuthViewModel,
    onForgotPassword: () -> Unit,
    gateErrorMessage: String?,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val form by viewModel.loginForm.collectAsStateWithLifecycle()
    LoginContent(
        form = form,
        gateErrorMessage = gateErrorMessage,
        onSubmit = viewModel::login,
        onForgotPassword = onForgotPassword,
        onRetry = onRetry,
        modifier = modifier,
    )
}

/**
 * Stateless login UI. Holds only the locally-entered field text and the
 * masked/plain toggle; all validation and network state live in [form].
 *
 * Behaviour:
 *  - Username and password fields; the password defaults to **masked** and a
 *    trailing control toggles it to plain text and back (R1.11).
 *  - The submit control is disabled while [LoginFormState.isSubmitting] so a second
 *    `POST /auth/login` can't be fired mid-flight (and shows a progress indicator).
 *  - Field-level validation messages render under each field
 *    ([LoginFormState.usernameError]/[LoginFormState.passwordError], R1.10); the
 *    form-level [LoginFormState.errorMessage] (Backend auth failure R1.8 /
 *    connection failure R1.9) renders above the submit control.
 *  - When [LoginFormState.passwordClearToken] changes (an authentication failure,
 *    R1.8) the password field is cleared while the **username is retained**.
 *  - A "Forgot password" entry point invokes [onForgotPassword] (R3.1 hook).
 */
@Composable
fun LoginContent(
    form: LoginFormState,
    gateErrorMessage: String?,
    onSubmit: (username: String, password: String) -> Unit,
    onForgotPassword: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // Locally-held field text. Username survives failed attempts (R1.8); password
    // is cleared reactively when the ViewModel bumps the clear token (below).
    var username by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var passwordVisible by rememberSaveable { mutableStateOf(false) }

    // Clear the password whenever the auth-failure clear-token changes (R1.8). The
    // token is the key, so this fires exactly on a new authentication failure and
    // never disturbs the retained username.
    LaunchedEffect(form.passwordClearToken) {
        if (form.passwordClearToken != 0) {
            password = ""
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp, vertical = 24.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = "TeleAutomation",
            style = MaterialTheme.typography.headlineMedium,
            textAlign = TextAlign.Center,
        )
        Text(
            text = "Telegram CRM · AI inbox · multi-account",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )

        // Auth-gate error (auth-status failure / timeout) with a retry that re-runs
        // the startup check while the stored session is retained (R1.4, R2.3).
        if (gateErrorMessage != null) {
            Text(
                text = gateErrorMessage,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = "Session error: $gateErrorMessage" },
            )
            TextButton(
                onClick = onRetry,
                enabled = !form.isSubmitting,
            ) {
                Text("Retry")
            }
        }

        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Username") },
            singleLine = true,
            enabled = !form.isSubmitting,
            isError = form.usernameError != null,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Text,
                imeAction = ImeAction.Next,
            ),
            supportingText = {
                if (form.usernameError != null) {
                    Text(
                        text = form.usernameError,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
        )

        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Password") },
            singleLine = true,
            enabled = !form.isSubmitting,
            isError = form.passwordError != null,
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
                val description = if (passwordVisible) "Hide password" else "Show password"
                IconButton(
                    onClick = { passwordVisible = !passwordVisible },
                    enabled = !form.isSubmitting,
                    modifier = Modifier.semantics { contentDescription = description },
                ) {
                    Icon(
                        imageVector = if (passwordVisible) {
                            Icons.Filled.Visibility
                        } else {
                            Icons.Filled.VisibilityOff
                        },
                        contentDescription = null,
                    )
                }
            },
            supportingText = {
                if (form.passwordError != null) {
                    Text(
                        text = form.passwordError,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
        )

        // Form-level error: Backend auth failure (R1.8) or connection failure (R1.9).
        if (form.errorMessage != null) {
            Text(
                text = form.errorMessage,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentDescription = "Login error: ${form.errorMessage}" },
            )
        }

        Button(
            onClick = { onSubmit(username, password) },
            enabled = !form.isSubmitting,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (form.isSubmitting) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            } else {
                Text("Sign in")
            }
        }

        TextButton(
            onClick = onForgotPassword,
            enabled = !form.isSubmitting,
            modifier = Modifier.semantics { contentDescription = "Forgot password" },
        ) {
            Text("Forgot password?")
        }

        Text(
            text = "Operator access only. Contact your admin if you need credentials.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun LoginContentPreview() {
    TeleAutomationTheme {
        LoginContent(
            form = LoginFormState(),
            gateErrorMessage = null,
            onSubmit = { _, _ -> },
            onForgotPassword = {},
            onRetry = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun LoginContentErrorPreview() {
    TeleAutomationTheme {
        LoginContent(
            form = LoginFormState(
                usernameError = "Enter your username.",
                errorMessage = "Invalid username or password.",
            ),
            gateErrorMessage = "Couldn't verify your session. Please sign in or try again.",
            onSubmit = { _, _ -> },
            onForgotPassword = {},
            onRetry = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun LoginContentSubmittingPreview() {
    TeleAutomationTheme {
        LoginContent(
            form = LoginFormState(isSubmitting = true),
            gateErrorMessage = null,
            onSubmit = { _, _ -> },
            onForgotPassword = {},
            onRetry = {},
        )
    }
}
