package com.teleautomation.android.core

/**
 * Pure, device-independent confirmation gate for destructive actions (R6.8, R6.9).
 *
 * Several destructive operations (the reach reset `POST /stats/reset`, and other
 * confirm-before-acting flows) must be guarded behind an explicit confirmation:
 * the Backend call is performed **only** when the Operator picks the explicit
 * confirm action, and the cancel action must never trigger it. This object models
 * that decision as a pure function so the gating rule can be unit/property tested on
 * the plain JVM, independent of Compose, OkHttp, or coroutines.
 *
 * Living in `core` (no Android/Retrofit/coroutine dependencies) is deliberate: the
 * UI half (the dialog) is built separately as
 * [com.teleautomation.android.ui.common.ConfirmDialog], and a ViewModel wires the
 * dialog's chosen [ConfirmationOutcome] to this gate, passing the actual Backend
 * call as the guarded action. Because the gate is the single place that decides
 * whether the action runs, both the dialog and the gate can be reused by every
 * confirmation-gated flow.
 *
 * Backing property (Property 8): for any confirmation-dialog outcome, the guarded
 * call is invoked if and only if the outcome is [ConfirmationOutcome.Confirm]; the
 * [ConfirmationOutcome.Cancel] outcome never invokes it.
 */
object ConfirmationGate {

    /**
     * Runs [guardedAction] if and only if [outcome] is the explicit
     * [ConfirmationOutcome.Confirm]; for [ConfirmationOutcome.Cancel] the action is
     * never evaluated (R6.8, R6.9).
     *
     * The result reports which branch was taken without side effects of its own:
     * - [ConfirmationDispatch.Invoked] carries the value produced by
     *   [guardedAction] and means the action ran (confirm path).
     * - [ConfirmationDispatch.NotInvoked] means the action was not evaluated
     *   (cancel path); the guarded call's parameters are left untouched so no
     *   destructive effect is implied.
     *
     * Evaluation is lazy: on the cancel path [guardedAction] is not called at all,
     * so passing a closure that performs the Backend call is safe.
     *
     * @param outcome the Operator's explicit choice from the confirmation dialog.
     * @param guardedAction the destructive action to run only on confirm; for the
     *   reach reset this is the `POST /stats/reset` call. Evaluated at most once.
     * @return [ConfirmationDispatch.Invoked] with the action's value on confirm, or
     *   [ConfirmationDispatch.NotInvoked] on cancel.
     */
    fun <T> dispatch(
        outcome: ConfirmationOutcome,
        guardedAction: () -> T,
    ): ConfirmationDispatch<T> = when (outcome) {
        ConfirmationOutcome.Confirm -> ConfirmationDispatch.Invoked(guardedAction())
        ConfirmationOutcome.Cancel -> ConfirmationDispatch.NotInvoked
    }

    /**
     * Whether [outcome] should trigger the guarded action (R6.8, R6.9).
     *
     * Returns `true` only for [ConfirmationOutcome.Confirm]. Provided as a pure
     * predicate for callers that need the decision without supplying an action
     * (for example, to enable/disable a control).
     */
    fun shouldInvoke(outcome: ConfirmationOutcome): Boolean =
        outcome == ConfirmationOutcome.Confirm
}

/**
 * The explicit outcome of a confirmation dialog (R6.8, R6.9).
 *
 * Only [Confirm] authorizes the guarded action; [Cancel] dismisses without acting.
 * Modeled as a sealed type (rather than a boolean) so the intent is explicit at
 * call sites and the gate cannot be driven by an ambiguous value.
 */
sealed interface ConfirmationOutcome {
    /** The Operator explicitly confirmed; the guarded action is authorized to run. */
    data object Confirm : ConfirmationOutcome

    /** The Operator explicitly cancelled; the guarded action must not run. */
    data object Cancel : ConfirmationOutcome
}

/**
 * Result of [ConfirmationGate.dispatch], reporting whether the guarded action ran.
 *
 * @param T the value type produced by the guarded action.
 */
sealed interface ConfirmationDispatch<out T> {
    /**
     * The confirm path was taken: the guarded action ran and produced [value].
     */
    data class Invoked<out T>(val value: T) : ConfirmationDispatch<T>

    /**
     * The cancel path was taken: the guarded action was not evaluated and no
     * destructive effect occurred.
     */
    data object NotInvoked : ConfirmationDispatch<Nothing>
}
