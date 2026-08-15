package com.teleautomation.android.ui.common

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.teleautomation.android.core.ConfirmationGate
import com.teleautomation.android.core.ConfirmationOutcome

/**
 * Reusable Material3 confirmation dialog for destructive actions (R6.8, R6.9).
 *
 * Presents a title, message, and two explicit choices — an affirmative confirm
 * action and a cancel action. The confirm control reports
 * [ConfirmationOutcome.Confirm] and the cancel control (and any dismissal, e.g. a
 * back press or outside tap) reports [ConfirmationOutcome.Cancel]. The dialog is
 * intentionally *decision-only*: it never performs the guarded Backend call itself.
 * Callers route the chosen [ConfirmationOutcome] through [ConfirmationGate] so the
 * destructive call runs **only** on confirm and **never** on cancel, satisfying the
 * gating rule shared by all confirm-before-acting flows (reach reset and other
 * destructive ops).
 *
 * Typical wiring in a screen/ViewModel (reach reset, R6.8/R6.9):
 * ```
 * if (showResetDialog) {
 *     ConfirmDialog(
 *         title = "Reset reach?",
 *         message = "This clears all posts-sent and reach figures. This cannot be undone.",
 *         confirmLabel = "Reset",
 *         cancelLabel = "Cancel",
 *         onOutcome = { outcome ->
 *             showResetDialog = false
 *             viewModel.onResetOutcome(outcome) // delegates to ConfirmationGate.dispatch(...)
 *         },
 *     )
 * }
 * ```
 *
 * Visibility is hoisted: render this composable only while the dialog should be
 * shown, and clear that flag inside [onOutcome]. A single [onOutcome] callback (in
 * preference to separate confirm/cancel callbacks) keeps the outcome explicit and
 * mirrors the pure [ConfirmationOutcome] type the gate consumes.
 *
 * @param title the dialog title.
 * @param message the explanatory body describing the consequence of confirming.
 * @param onOutcome invoked with [ConfirmationOutcome.Confirm] when the Operator
 *   activates the confirm control, or [ConfirmationOutcome.Cancel] when the Operator
 *   activates cancel or dismisses the dialog.
 * @param confirmLabel label for the affirmative action; defaults to "Confirm".
 * @param cancelLabel label for the dismissive action; defaults to "Cancel".
 * @param destructive when `true` (the default) the confirm label is tinted with the
 *   theme error color to signal a destructive consequence.
 */
@Composable
fun ConfirmDialog(
    title: String,
    message: String,
    onOutcome: (ConfirmationOutcome) -> Unit,
    modifier: Modifier = Modifier,
    confirmLabel: String = "Confirm",
    cancelLabel: String = "Cancel",
    destructive: Boolean = true,
) {
    AlertDialog(
        onDismissRequest = { onOutcome(ConfirmationOutcome.Cancel) },
        modifier = modifier,
        title = { Text(text = title) },
        text = { Text(text = message) },
        confirmButton = {
            TextButton(onClick = { onOutcome(ConfirmationOutcome.Confirm) }) {
                Text(
                    text = confirmLabel,
                    color = if (destructive) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                )
            }
        },
        dismissButton = {
            TextButton(onClick = { onOutcome(ConfirmationOutcome.Cancel) }) {
                Text(text = cancelLabel)
            }
        },
    )
}
