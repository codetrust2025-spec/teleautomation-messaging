package com.teleautomation.android.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.teleautomation.android.core.realtime.ConnectionState
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Offline indicator bound to the realtime connection state (R22.7).
 *
 * Renders a slim banner whenever the realtime `/ws` stream is **not** established
 * — i.e. for any [ConnectionState] other than [ConnectionState.Connected]
 * ([ConnectionState.Connecting], [ConnectionState.Disconnected], or
 * [ConnectionState.Offline]). When the stream is connected the banner is hidden,
 * occupying no space.
 *
 * This composable is stateless: callers observe `RealtimeClient.connectionState`
 * (a `StateFlow<ConnectionState>`) and pass the latest value in, e.g.
 * `OfflineBanner(connectionState = realtimeClient.connectionState
 *     .collectAsStateWithLifecycle().value)`. Keeping it stateless makes it
 * previewable and testable without Hilt or a live socket.
 *
 * @param connectionState the current realtime connection state.
 * @param modifier applied to the banner container.
 */
@Composable
fun OfflineBanner(
    connectionState: ConnectionState,
    modifier: Modifier = Modifier,
) {
    val message = offlineMessageFor(connectionState)

    AnimatedVisibility(
        visible = message != null,
        enter = fadeIn() + expandVertically(),
        exit = fadeOut() + shrinkVertically(),
        modifier = modifier,
    ) {
        // `message` is non-null whenever this branch is visible; fall back
        // defensively so an exit animation frame can never crash.
        val text = message ?: offlineMessageFor(ConnectionState.Disconnected).orEmpty()
        OfflineBannerContent(text = text)
    }
}

/**
 * The user-facing banner text for a [state], or `null` when connected (no banner).
 * Separated out as pure logic so the show/hide decision and copy are testable.
 */
internal fun offlineMessageFor(state: ConnectionState): String? = when (state) {
    ConnectionState.Connected -> null
    ConnectionState.Connecting -> "Connecting…"
    ConnectionState.Disconnected -> "Offline — reconnecting…"
    ConnectionState.Offline -> "Offline — no Backend configured"
}

@Composable
private fun OfflineBannerContent(text: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.errorContainer)
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .semantics { contentDescription = text },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(
            imageVector = Icons.Filled.CloudOff,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onErrorContainer,
        )
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onErrorContainer,
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun OfflineBannerDisconnectedPreview() {
    TeleAutomationTheme {
        OfflineBanner(connectionState = ConnectionState.Disconnected)
    }
}

@Preview(showBackground = true)
@Composable
private fun OfflineBannerOfflinePreview() {
    TeleAutomationTheme {
        OfflineBanner(connectionState = ConnectionState.Offline)
    }
}
