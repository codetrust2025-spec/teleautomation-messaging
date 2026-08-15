package com.teleautomation.android.core

/**
 * Pure, device-independent gate for the Operator login form (R1.10).
 *
 * This logic lives in `core` (no Android, OkHttp, or Retrofit dependencies) so it is
 * unit/property testable on the plain JVM. The `AuthViewModel`/`LoginScreen` delegate
 * here before deciding whether to invoke the repository's `POST /auth/login` call.
 *
 * Backing requirement (R1.10): if the username field is empty OR the password field
 * is empty when the Operator submits the login form, the app must surface a
 * validation message identifying the empty field and must NOT call the Backend login
 * endpoint.
 *
 * Backing property (Property 1): for any username and password strings, the
 * submission is allowed — and only then is `POST /auth/login` invoked — if and only
 * if both fields are non-empty after trimming whitespace; otherwise the submission is
 * rejected, the offending field(s) is/are identified, and the login endpoint is not
 * called.
 *
 * Submission shape mirrors the Web_App reference (`LoginScreen.jsx`): the username is
 * submitted trimmed while the password is submitted exactly as entered (passwords may
 * legitimately contain leading/trailing whitespace); only the emptiness *gate* uses
 * the trimmed length of each field.
 */
object LoginInputValidator {

    /**
     * Validates the entered [username] and [password] without any side effects.
     *
     * Returns [LoginValidationResult.Valid] — carrying the trimmed username and the
     * raw password ready to hand to the login call — when both fields are non-empty
     * after trimming. Otherwise returns [LoginValidationResult.Invalid] naming every
     * empty field so the caller can highlight each one and must skip the network
     * call.
     */
    fun validate(username: String, password: String): LoginValidationResult {
        val emptyFields = buildSet {
            if (username.trim().isEmpty()) add(LoginField.USERNAME)
            if (password.trim().isEmpty()) add(LoginField.PASSWORD)
        }

        return if (emptyFields.isEmpty()) {
            LoginValidationResult.Valid(username = username.trim(), password = password)
        } else {
            LoginValidationResult.Invalid(emptyFields)
        }
    }
}

/** The two fields of the login form that the gate can flag as empty (R1.10). */
enum class LoginField { USERNAME, PASSWORD }

/** Outcome of gating a login submission via [LoginInputValidator.validate]. */
sealed interface LoginValidationResult {
    /**
     * The submission is allowed; the caller may invoke `POST /auth/login`.
     *
     * @property username the trimmed username to submit.
     * @property password the password to submit, preserved exactly as entered.
     */
    data class Valid(val username: String, val password: String) : LoginValidationResult

    /**
     * The submission is rejected; the caller must NOT invoke the login endpoint and
     * must surface a validation message for each flagged field.
     *
     * @property emptyFields the non-empty set of fields that were blank after
     *   trimming. Contains [LoginField.USERNAME], [LoginField.PASSWORD], or both.
     */
    data class Invalid(val emptyFields: Set<LoginField>) : LoginValidationResult
}
