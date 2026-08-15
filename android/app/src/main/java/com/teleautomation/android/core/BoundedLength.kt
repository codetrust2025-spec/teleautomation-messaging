package com.teleautomation.android.core

/**
 * Pure, device-independent bounded-length field validator (R3.5, R7.5, R7.6).
 *
 * This logic lives in `core` (no Android, OkHttp, or Retrofit dependencies) so it
 * is unit/property testable on the plain JVM. Presentation/ViewModel code
 * delegates to it to decide whether a text field may be submitted; the
 * corresponding Backend call is made only when the result is
 * [BoundedLengthResult.Accepted]. It is the single reusable validator shared by
 * the authenticated change-password flow (bounds `[8,128]`, tasks plan 6.8) and
 * the account display-name flow (bounds `[1,64]`, tasks plan 10.2).
 *
 * Backing requirements:
 * - R3.5: a changed password value must be between 8 and 128 characters.
 * - R7.5/R7.6: an edited account display name of 1 to 64 characters is submitted,
 *   while an empty or over-length name is rejected without calling the Backend.
 *
 * Backing property (Property 2): for any input string and any inclusive bounds
 * `[min,max]`, the validator accepts the input iff its effective length (after the
 * configured [TrimPolicy]) is within `[min,max]`; rejected inputs do not trigger
 * the corresponding Backend call.
 *
 * ### Trimming policy
 *
 * Whether surrounding whitespace counts toward the measured length is **explicit
 * and caller-controlled** via [TrimPolicy], because the right answer differs by
 * field:
 * - Passwords ([TrimPolicy.PRESERVE]): leading/trailing whitespace is significant
 *   and must be counted, since it is part of the secret. This is the default.
 * - Display names ([TrimPolicy.TRIM]): surrounding whitespace is cosmetic, so a
 *   name that is only spaces (or padded) is measured by its trimmed content,
 *   ensuring an effectively empty name is rejected against a `min` of 1.
 *
 * The validator never mutates or returns the input; [TrimPolicy] only affects
 * which character count is compared against the bounds.
 */
object BoundedLengthPolicy {

    /** How surrounding whitespace is treated when measuring an input's length. */
    enum class TrimPolicy {
        /** Count the input exactly as given; whitespace is significant (passwords). */
        PRESERVE,

        /** Measure the length after trimming surrounding whitespace (display names). */
        TRIM,
    }

    /**
     * Validates that [input] has a length within the inclusive range `[min,max]`
     * after applying [trim], without any side effects.
     *
     * Returns [BoundedLengthResult.Accepted] iff the effective length is `>= min`
     * and `<= max`; otherwise returns [BoundedLengthResult.Rejected] with a
     * human-readable reason (and the [BoundedLengthResult.Rejected.tooShort] flag)
     * describing whether the value was too short or too long. Callers must not
     * invoke the corresponding Backend call when the result is
     * [BoundedLengthResult.Rejected].
     *
     * @param input the candidate field value.
     * @param min the inclusive minimum length; must be `>= 0`.
     * @param max the inclusive maximum length; must be `>= min`.
     * @param trim how surrounding whitespace is treated; defaults to
     *   [TrimPolicy.PRESERVE] so the safe choice for secrets is the default.
     * @throws IllegalArgumentException if `min < 0` or `max < min` (a misconfigured
     *   bound is a programming error, not a user-input error).
     */
    fun validate(
        input: String,
        min: Int,
        max: Int,
        trim: TrimPolicy = TrimPolicy.PRESERVE,
    ): BoundedLengthResult {
        require(min >= 0) { "Minimum length must be >= 0, was $min." }
        require(max >= min) { "Maximum length ($max) must be >= minimum length ($min)." }

        val measured = when (trim) {
            TrimPolicy.PRESERVE -> input
            TrimPolicy.TRIM -> input.trim()
        }
        val length = measured.length

        return when {
            length < min -> BoundedLengthResult.Rejected(
                reason = "Must be at least $min character${plural(min)} (was $length).",
                tooShort = true,
            )
            length > max -> BoundedLengthResult.Rejected(
                reason = "Must be at most $max character${plural(max)} (was $length).",
                tooShort = false,
            )
            else -> BoundedLengthResult.Accepted
        }
    }

    private fun plural(n: Int): String = if (n == 1) "" else "s"
}

/** Outcome of validating a field length via [BoundedLengthPolicy.validate]. */
sealed interface BoundedLengthResult {
    /** The input length is within the inclusive bounds; the field may be submitted. */
    data object Accepted : BoundedLengthResult

    /**
     * The input length is outside the inclusive bounds; the field must not be
     * submitted. [reason] is a human-readable explanation and [tooShort] is `true`
     * when the value was below `min` and `false` when it exceeded `max`.
     */
    data class Rejected(val reason: String, val tooShort: Boolean) : BoundedLengthResult
}
