package com.teleautomation.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.teleautomation.android.ui.auth.AuthGate
import com.teleautomation.android.ui.theme.TeleAutomationTheme
import dagger.hilt.android.AndroidEntryPoint

/**
 * Single entry-point activity for the TeleAutomation Android client.
 *
 * The activity hosts the [AuthGate], which observes `AuthViewModel.uiState` and
 * switches the whole app between the splash (startup auth-status check, R1.1), the
 * login screen (no/expired session, R1.2/R1.5), and the role-based navigation shell
 * (authenticated, R1.3/R2.1/R2.7). All auth logic lives in the ViewModel; this
 * activity only sets up the Compose + theme baseline and renders the gate (MVVM).
 *
 * Annotated [AndroidEntryPoint] so Hilt can provide the activity-scoped
 * `AuthViewModel` (and its repository graph) to the composables via `hiltViewModel()`.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            TeleAutomationApp()
        }
    }
}

/**
 * App root: applies the [TeleAutomationTheme] and renders the [AuthGate] on a
 * full-size themed surface.
 */
@Composable
private fun TeleAutomationApp() {
    TeleAutomationTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            AuthGate()
        }
    }
}
