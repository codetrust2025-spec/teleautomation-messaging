package com.teleautomation.android.ui.nav

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.teleautomation.android.ui.theme.TeleAutomationTheme

/**
 * Temporary destination content used by [NavScaffold] for modules whose real
 * screens are built in later tasks (Dashboard task 9.x, Inbox task 15.x, etc.).
 *
 * It exists so the navigation shell compiles and is fully navigable now: every
 * role-resolved route resolves to a visible, titled screen. Later tasks replace
 * the per-route `composable { ... }` bodies in [NavScaffold] with the real
 * screens; this composable is then no longer referenced.
 *
 * @param title the human-readable module name shown as the screen heading.
 * @param modifier applied to the screen container.
 */
@Composable
fun PlaceholderScreen(
    title: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp)
            .semantics { contentDescription = "$title placeholder" },
        verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.headlineSmall,
            textAlign = TextAlign.Center,
        )
        Text(
            text = "Coming soon",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun PlaceholderScreenPreview() {
    TeleAutomationTheme {
        PlaceholderScreen(title = "Dashboard")
    }
}
