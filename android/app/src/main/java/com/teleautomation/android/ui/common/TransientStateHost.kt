package com.teleautomation.android.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.teleautomation.android.core.ErrorKind
import com.teleautomation.android.core.ViewState
import kotlinx.coroutines.delay

/**
 * Renders the transient state of a single data-backed view from a pure
 * [ViewState] (R25.1–R25.5).
 *
 * This is a stateless, presentation-only host: the loading / empty / content /
 * error decision is made upstream by
 * [com.teleautomation.android.core.ViewStateSelector] and handed in as [state].
 * The host only paints whichever case it receives:
 *  - [ViewState.Loading] → [loadingIndicator] (R25.1).
 *  - [ViewState.EmptyState] → [emptyState] (R25.2).
 *  - [ViewState.Content] → [content] with the produced data.
 *  - [ViewState.ErrorWithRetry] → an error message plus a retry control wired to
 *    [onRetry]; when the error carries
 *    [retained data][ViewState.ErrorWithRetry.retainedData] the previously
 *    displayed [content] stays visible behind the error indication so data is not
 *    lost on failure (R25.4, R25.5).
 *
 * The retry control is wired to [onRetry], which callers wire to re-issue the
 * failed request via the closure carried on
 * [ViewState.ErrorWithRetry.retry] — for example
 * `onRetry = { scope.launch { viewModel.reissue(state.retry) } }`. Keeping the
 * suspend re-issue in the caller (the ViewModel) preserves the MVVM split and
 * keeps this composable free of coroutine/state ownership.
 *
 * @param state the view state to render.
 * @param onRetry invoked when the Operator activates the retry control; should
 *   re-issue the failed Backend request (R25.5).
 * @param emptyMessage message shown by the default [emptyState] (R25.2).
 * @param loadingIndicator slot for the loading affordance; defaults to a centered
 *   progress indicator.
 * @param emptyState slot for the empty-state affordance; defaults to a centered
 *   [emptyMessage].
 * @param content renders the successful data; also used to keep retained data
 *   visible behind an error.
 */
@Composable
fun <T> TransientStateHost(
    state: ViewState<T>,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    emptyMessage: String = "No data available.",
    loadingIndicator: @Composable () -> Unit = { DefaultLoadingIndicator() },
    emptyState: @Composable () -> Unit = { DefaultEmptyState(message = emptyMessage) },
    content: @Composable (T) -> Unit,
) {
    Box(modifier = modifier.fillMaxSize()) {
        when (state) {
            is ViewState.Loading -> loadingIndicator()

            is ViewState.EmptyState -> emptyState()

            is ViewState.Content -> content(state.data)

            is ViewState.ErrorWithRetry -> {
                val retained = state.retainedData
                if (retained != null) {
                    // Keep the last displayed data visible (R25.4) with the error and
                    // retry surfaced above it.
                    Column(modifier = Modifier.fillMaxSize()) {
                        ErrorBanner(message = state.message, onRetry = onRetry)
                        Box(modifier = Modifier.fillMaxSize()) { content(retained) }
                    }
                } else {
                    ErrorWithRetryState(message = state.message, onRetry = onRetry)
                }
            }
        }
    }
}

/** Centered progress indicator used as the default loading affordance (R25.1). */
@Composable
fun DefaultLoadingIndicator(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .semantics { contentDescription = "Loading" },
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator()
    }
}

/** Centered empty-state message used as the default empty affordance (R25.2). */
@Composable
fun DefaultEmptyState(message: String, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}

/**
 * Full-view error state with a retry control, shown when there is no previously
 * displayed data to retain (R25.4, R25.5).
 */
@Composable
fun ErrorWithRetryState(
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
                textAlign = TextAlign.Center,
            )
            Button(onClick = onRetry) {
                Icon(
                    imageVector = Icons.Filled.Refresh,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Text(
                    text = "Retry",
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
        }
    }
}

/**
 * Compact error banner with a retry control, shown above retained data so the
 * Operator keeps seeing the last loaded content while a failure is surfaced
 * (R25.4, R25.5).
 */
@Composable
private fun ErrorBanner(
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = message,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
            )
            Button(onClick = onRetry) {
                Icon(
                    imageVector = Icons.Filled.Refresh,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                )
                Text(
                    text = "Retry",
                    modifier = Modifier.padding(start = 6.dp),
                )
            }
        }
    }
}

/**
 * Maps an [ErrorKind] to a default, human-readable view message. Callers may pass
 * their own message through [ViewState.ErrorWithRetry.message]; this helper gives a
 * sensible fallback consistent with the resilience requirements (R26.1–R26.4).
 */
fun defaultMessageFor(kind: ErrorKind): String = when (kind) {
    ErrorKind.Offline -> "You appear to be offline. Check your connection and try again."
    ErrorKind.Timeout -> "The request timed out. Please try again."
    ErrorKind.Server5xx -> "The server ran into a problem. Please try again."
    ErrorKind.Unauthorized -> "Your session has expired. Please sign in again."
    ErrorKind.Client4xx -> "The request could not be completed."
    ErrorKind.Unknown -> "Something went wrong. Please try again."
}

/**
 * Success-confirmation host that stays visible for at least [minVisibleMillis]
 * (default 3 seconds) or until the Operator dismisses it (R25.3).
 *
 * Pass a non-null [message] when a Backend write operation succeeds; the host shows
 * the confirmation and, after [minVisibleMillis], auto-dismisses by invoking
 * [onDismiss]. The Operator may dismiss earlier with the close control, which also
 * invokes [onDismiss]. Driving visibility through a hoisted [message] keeps the
 * confirmation state owned by the caller (typically a ViewModel), matching the MVVM
 * split used elsewhere.
 *
 * @param message the confirmation text to show, or `null` to render nothing.
 * @param onDismiss invoked when the confirmation should be cleared (after the
 *   minimum visible window elapses or on explicit dismissal).
 * @param minVisibleMillis the minimum time the confirmation stays visible before
 *   auto-dismissal; must be `>= 3000` to satisfy R25.3. Defaults to 3000.
 */
@Composable
fun SuccessConfirmationHost(
    message: String?,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    minVisibleMillis: Long = MIN_SUCCESS_VISIBLE_MILLIS,
) {
    if (message == null) return

    // Hold the confirmation for the minimum window, then auto-dismiss (R25.3). Keyed
    // on the message so a new confirmation restarts the timer.
    LaunchedEffect(message, minVisibleMillis) {
        delay(minVisibleMillis.coerceAtLeast(MIN_SUCCESS_VISIBLE_MILLIS))
        onDismiss()
    }

    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.primaryContainer,
        contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Filled.CheckCircle,
                contentDescription = null,
            )
            Text(
                text = message,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium,
            )
            IconButton(onClick = onDismiss) {
                Icon(
                    imageVector = Icons.Filled.Close,
                    contentDescription = "Dismiss confirmation",
                )
            }
        }
    }
}

/** Minimum time a success confirmation stays visible before auto-dismissal (R25.3). */
const val MIN_SUCCESS_VISIBLE_MILLIS: Long = 3_000L
