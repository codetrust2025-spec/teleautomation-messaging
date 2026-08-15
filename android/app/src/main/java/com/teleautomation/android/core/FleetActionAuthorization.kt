package com.teleautomation.android.core

/**
 * Reusable handling of a Backend **HTTP 403 Forbidden** response on a fleet-control
 * action (R4.6).
 *
 * The Backend gates fleet-control actions behind `_require_fleet_admin`; when an
 * Operator who is not permitted attempts such an action the Backend answers `403`.
 * Per R4.6 the Android_App must then surface an *authorization* error and leave local
 * state unchanged so that no successful outcome is implied.
 *
 * [NetworkErrorClassifier] correctly folds every non-401 4xx into
 * [ErrorKind.Client4xx] for view-state purposes; this helper recovers the specific
 * `403` case from the retained [NetworkResult.Error.httpStatus] and turns it into a
 * single, explicit UI signal that fleet-action ViewModels (built in later tasks) can
 * consume uniformly.
 *
 * Usage contract for ViewModels (the "leave local state unchanged" half of R4.6):
 * apply state mutations *only* on [NetworkResult.Success]; on a forbidden result
 * surface [FleetActionAuthorization.authorizationSignal] (or the message from
 * [forbiddenAuthorizationError]) and make no optimistic/local change, so the failed
 * action never reads as if it succeeded.
 *
 * These functions are pure and live in `core` (no Android/OkHttp/Retrofit
 * dependencies) so they are unit testable on the plain JVM.
 */
object FleetActionAuthorization {

    /**
     * The authorization error surfaced for a forbidden fleet-control action (R4.6).
     * Phrased as an *authorization* failure (not a generic client error) so the UI
     * makes clear the action was not permitted rather than implying it completed.
     */
    const val MESSAGE: String =
        "You are not authorized to perform this action. Your role does not permit this fleet-control operation."

    /** The single UI signal emitted for a forbidden fleet-control action. */
    val authorizationSignal: AuthorizationSignal = AuthorizationSignal(MESSAGE)
}

/**
 * An explicit, UI-agnostic authorization-error signal raised when a permitted-only
 * action is refused (R4.4 navigation guard, R4.6 fleet-action 403). Carrying a small
 * value type rather than a bare string lets callers (snackbar host, screen state)
 * react to "authorization denied" distinctly from other error text.
 *
 * @param message the human-readable authorization error to display.
 */
data class AuthorizationSignal(val message: String)

/**
 * Whether this result is a Backend **HTTP 403 Forbidden** failure (R4.6).
 *
 * True only for a [NetworkResult.Error] whose retained status is exactly `403`
 * (see [NetworkErrorClassifier.isForbidden]); every other outcome — success, empty,
 * loading, or a non-403 error — is `false`.
 */
fun NetworkResult<*>.isForbidden(): Boolean =
    this is NetworkResult.Error && NetworkErrorClassifier.isForbidden(httpStatus)

/**
 * The authorization-error message for a forbidden fleet-control action, or `null`
 * when this result is not a `403` failure (R4.6).
 *
 * A `null` return means there is no authorization error to surface — the caller
 * should fall back to its normal success/empty/error handling and, crucially, must
 * not treat a non-forbidden failure as a successful outcome.
 */
fun NetworkResult<*>.forbiddenAuthorizationError(): String? =
    if (isForbidden()) FleetActionAuthorization.MESSAGE else null

/**
 * The [AuthorizationSignal] for a forbidden fleet-control action, or `null` when this
 * result is not a `403` failure (R4.6). Convenience wrapper over
 * [forbiddenAuthorizationError] for callers that route a typed signal.
 */
fun NetworkResult<*>.forbiddenAuthorizationSignal(): AuthorizationSignal? =
    if (isForbidden()) FleetActionAuthorization.authorizationSignal else null
