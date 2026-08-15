package com.teleautomation.android.ui.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.teleautomation.android.core.realtime.ConnectionState
import com.teleautomation.android.presentation.AuthUiState
import com.teleautomation.android.presentation.AuthViewModel
import com.teleautomation.android.ui.nav.NavScaffold
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Top-level **auth-gate** that switches the whole app between the splash, the login
 * screen, and the authenticated navigation shell based on [AuthViewModel.uiState]
 * (R1.1–R1.5, R1.7, R2.1, R2.7).
 *
 *  - [AuthUiState.Loading] → a centered splash/progress while the startup
 *    auth-status check is in flight (R1.1).
 *  - [AuthUiState.Unauthenticated] → the [LoginScreen]; its `errorMessage`
 *    (auth-status failure / 10s timeout) is shown with a retry that re-runs the
 *    gate while the stored session is retained (R1.4, R2.3). A "Forgot password"
 *    entry point toggles into the self-service reset flow (the real screen lands in
 *    task 6.8; [ForgotPasswordPlaceholder] is the navigation target until then).
 *  - [AuthUiState.Authenticated] → the [NavScaffold] for the Operator's role, with
 *    the username shown in the navigation area and a sign-out hook wired to
 *    [AuthViewModel.logout] (R2.7).
 *
 * The realtime [inboxUnreadCount]/[connectionState] inputs default to a quiet,
 * disconnected baseline; the realtime tasks (30.x) supply live values.
 *
 * @param authViewModel the shared auth ViewModel (defaults to the Hilt-provided
 *   activity-scoped instance).
 * @param inboxUnreadCount Inbox unread count forwarded to the shell badge.
 * @param connectionState realtime connection state forwarded to the shell.
 * @param modifier applied to the gate container.
 */
@Composable
fun AuthGate(
    modifier: Modifier = Modifier,
    authViewModel: AuthViewModel = hiltViewModel(),
    inboxUnreadCount: Int = 0,
    connectionState: ConnectionState = ConnectionState.Disconnected,
) {
    val uiState by authViewModel.uiState.collectAsStateWithLifecycle()

    // Local toggle for the self-service reset flow reachable from the login screen
    // (R3.1). The real reset screen is built in task 6.8; this gate only owns the
    // navigation hook between login and that flow.
    var forgotPasswordRequested by remember { mutableStateOf(false) }

    when (val state = uiState) {
        AuthUiState.Loading -> SplashScreen(modifier = modifier)

        is AuthUiState.Unauthenticated ->
            if (forgotPasswordRequested) {
                ForgotPasswordPlaceholder(
                    onBack = { forgotPasswordRequested = false },
                    modifier = modifier,
                )
            } else {
                LoginScreen(
                    viewModel = authViewModel,
                    onForgotPassword = { forgotPasswordRequested = true },
                    gateErrorMessage = state.errorMessage,
                    onRetry = authViewModel::retryAuthGate,
                    modifier = modifier,
                )
            }

        is AuthUiState.Authenticated -> {
            // Leaving the unauthenticated branch invalidates any pending reset hop so
            // a later sign-out returns to the login screen, not the reset placeholder.
            LaunchedEffect(Unit) { forgotPasswordRequested = false }
            NavScaffold(
                role = state.role,
                username = state.username,
                inboxUnreadCount = inboxUnreadCount,
                connectionState = connectionState,
                onLogout = authViewModel::logout,
                modifier = modifier,
            )
        }
    }
}

/**
 * Centered splash shown while the startup auth-status check resolves (R1.1).
 */
@Composable
fun SplashScreen(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp)
            .semantics { contentDescription = "Loading" },
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CircularProgressIndicator()
        Text(
            text = "Loading…",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * Temporary navigation target for the "Forgot password" entry point. The real
 * self-service reset flow is implemented in task 6.8 (R3.1–R3.4), which replaces
 * this placeholder in [AuthGate]. It exists now so the entry point is a working,
 * reversible navigation hop rather than a dead control.
 */
@Composable
fun ForgotPasswordPlaceholder(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp)
            .semantics { contentDescription = "Forgot password placeholder" },
        verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = "Reset password",
            style = MaterialTheme.typography.headlineSmall,
            textAlign = TextAlign.Center,
        )
        Text(
            text = "Self-service reset is coming soon.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        TextButton(onClick = onBack) {
            Text("Back to sign in")
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun SplashScreenPreview() {
    TeleAutomationTheme {
        SplashScreen()
    }
}

@Preview(showBackground = true)
@Composable
private fun ForgotPasswordPlaceholderPreview() {
    TeleAutomationTheme {
        ForgotPasswordPlaceholder(onBack = {})
    }
}
