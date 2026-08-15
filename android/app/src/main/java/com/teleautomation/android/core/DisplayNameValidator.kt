package com.teleautomation.android.core

/**
 * Pure, device-independent validator for an account display name (R7.5, R7.6).
 *
 * This logic lives in `core` (no Android, OkHttp, or Retrofit dependencies) so it is
 * unit/property testable on the plain JVM. The Accounts screen / ViewModel (tasks plan
 * 10.3) delegates here before deciding whether to invoke the Backend display-name
 * endpoint (`POST /account/{slot}/display-name`): the call is made only when the result
 * is [BoundedLengthResult.Accepted].
 *
 * Rather than duplicating the length-check logic, this object is a thin, named wrapper
 * around the shared [BoundedLengthPolicy] that pins the display-name bounds `[1,64]` and
 * the [BoundedLengthPolicy.TrimPolicy.TRIM] policy in one place, so every call site and
 * the Property 2 test usage for `[1,64]` stay clear, consistent, and reusable.
 *
 * Backing requirements:
 * - R7.5: an edited account display name of 1 to 64 characters is submitted to the
 *   Backend display-name endpoint.
 * - R7.6: a display name that is empty (including whitespace-only) or exceeds 64
 *   characters is rejected with an invalid-length error and the Backend is NOT called.
 *
 * Backing property (Property 2): for any input string, the validator accepts it iff its
 * trimmed length is within the inclusive bounds `[1,64]`; rejected inputs do not trigger
 * the corresponding Backend call.
 *
 * The display name is measured after trimming surrounding whitespace
 * ([BoundedLengthPolicy.TrimPolicy.TRIM]), so a name consisting only of spaces is treated
 * as effectively empty and rejected against the minimum of 1. The validator never mutates
 * or returns the input; callers that submit should trim the name themselves to match the
 * measured value.
 */
object DisplayNameValidator {

    /** Inclusive minimum length of an account display name (R7.5, R7.6). */
    const val MIN_LENGTH: Int = 1

    /** Inclusive maximum length of an account display name (R7.5, R7.6). */
    const val MAX_LENGTH: Int = 64

    /**
     * Validates that [name] is a usable account display name without any side effects.
     *
     * Returns [BoundedLengthResult.Accepted] iff the trimmed length of [name] is within
     * the inclusive range `[1,64]`; otherwise returns [BoundedLengthResult.Rejected] with
     * a human-readable reason. Callers must not invoke the Backend display-name endpoint
     * when the result is [BoundedLengthResult.Rejected].
     */
    fun validate(name: String): BoundedLengthResult =
        BoundedLengthPolicy.validate(
            input = name,
            min = MIN_LENGTH,
            max = MAX_LENGTH,
            trim = BoundedLengthPolicy.TrimPolicy.TRIM,
        )
}
