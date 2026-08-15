package com.teleautomation.android.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.teleautomation.android.core.BoundedLengthPolicy
import com.teleautomation.android.core.BoundedLengthResult
import com.teleautomation.android.core.NetworkResult
import com.teleautomation.android.data.repo.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import javax.inject.Inject

/**
 * Immutable UI state for the self-service password reset flow (R3.1, R3.2, R3.4).
 *
 * The Backend `POST /auth/reset-password` endpoint requires three fields —
 * `username`, `reference`, and `new_password` (verified against
 * `core/dashboard_auth_api.py`) — so the form collects exactly those. The new
 * password is gated by the shared `[8,128]` [BoundedLengthPolicy] validator before
 * any Backend call (Property 2); the username and reference are gated as
 * non-empty so an obviously incomplete request never reaches the Backend.
 *
 * On failure all entered values are retained so the Operator can correct and retry
 * (R3.4); on success a confirmation is surfaced (R3.3).
 *
 * @property username the Handler username for the reset.
 * @property reference the Handler reference id required by the Backend.
 * @property newPassword the proposed new password (validated `[8,128]`).
 * @property usernameError inline validation message when [username] is empty;
 *   `null` otherwise.
 * @property referenceError inline validation message when [reference] is empty;
 *   `null` otherwise.
 * @property newPasswordError inline validation message when [newPassword] is
 *   outside `[8,128]`; `null` otherwise.
 * @property isSubmitting whether a reset request is in flight (disables the submit
 *   control and avoids duplicate submissions).
 * @property errorMessage the Backend/connection error from the last attempt (R3.4),
 *   or `null` when there is none.
 * @property successMessage a confirmation shown after a successful reset (R3.3), or
 *   `null` when there is nothing to confirm.
 */
data class ForgotPasswordUiState(
    val username: String = "",
    val reference: String = "",
    val newPassword: String = "",
    val usernameError: String? = null,
    val referenceError: String? = null,
    val newPasswordError: String? = null,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val successMessage: String? = null,
)

/**
 * Presentation-layer ViewModel for
 * [com.teleautomation.android.ui.auth.ForgotPasswordScreen] (R3.1, R3.2, R3.4).
 *
 * Holds the reset-flow form state, validates inputs in the pure logic layer, and
 * delegates the Backend round-trip to [AuthRepository.resetPassword]. The screen
 * renders [uiState] and forwards intents ([onUsernameChanged], [onReferenceChanged],
 * [onNewPasswordChanged], [onSubmit]) — it contains no business logic (MVVM).
 *
 * Submission is gated by [BoundedLengthPolicy] for the new password (`[8,128]`,
 * Property 2) plus non-empty checks for the username and reference; if any field is
 * invalid the offending field is identified inline and the Backend is **not**
 * called. A valid submission calls `POST /auth/reset-password` under a 30s
 * functional bound: a success surfaces a confirmation (R3.3), while a Backend error
 * or the 30s timeout surfaces an error and retains all entered values for retry
 * (R3.4).
 */
@HiltViewModel
class ForgotPasswordViewModel @Inject constructor(
    private val authRepository: AuthRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ForgotPasswordUiState())
    val uiState: StateFlow<ForgotPasswordUiState> = _uiState.asStateFlow()

    /** Records the latest username text and clears stale field/result messages. */
    fun onUsernameChanged(value: String) {
        _uiState.update {
            it.copy(
                username = value,
                usernameError = null,
                errorMessage = null,
                successMessage = null,
            )
        }
    }

    /** Records the latest reference text and clears stale field/result messages. */
    fun onReferenceChanged(value: String) {
        _uiState.update {
            it.copy(
                reference = value,
                referenceError = null,
                errorMessage = null,
                successMessage = null,
            )
        }
    }

    /** Records the latest new-password text and clears stale field/result messages. */
    fun onNewPasswordChanged(value: String) {
        _uiState.update {
            it.copy(
                newPassword = value,
                newPasswordError = null,
                errorMessage = null,
                successMessage = null,
            )
        }
    }

    /** Clears the success confirmation once its visible window elapses (R25.3). */
    fun onSuccessConfirmationDismissed() {
        _uiState.update { it.copy(successMessage = null) }
    }

    /**
     * Validates the form and, when valid, submits the reset request (R3.2, R3.4).
     *
     * Identifies every offending field inline and skips the Backend call when any
     * field is invalid. On a valid submission it calls
     * [AuthRepository.resetPassword] under a 30s functional bound and maps the
     * outcome to a confirmation (R3.3) or a retained-input error (R3.4).
     */
    fun onSubmit() {
        val current = _uiState.value
        val username = current.username
        val reference = current.reference
        val newPassword = current.newPassword

        val usernameError = if (username.trim().isEmpty()) USERNAME_REQUIRED_MESSAGE else null
        val referenceError = if (reference.trim().isEmpty()) REFERENCE_REQUIRED_MESSAGE else null
        val newPasswordError =
            when (val result = BoundedLengthPolicy.validate(newPassword, PASSWORD_MIN, PASSWORD_MAX)) {
                is BoundedLengthResult.Rejected -> result.reason
                BoundedLengthResult.Accepted -> null
            }

        if (usernameError != null || referenceError != null || newPasswordError != null) {
            _uiState.update {
                it.copy(
                    usernameError = usernameError,
                    referenceError = referenceError,
                    newPasswordError = newPasswordError,
                    errorMessage = null,
                    successMessage = null,
                )
            }
            return
        }

        _uiState.update {
            it.copy(
                isSubmitting = true,
                usernameError = null,
                referenceError = null,
                newPasswordError = null,
                errorMessage = null,
                successMessage = null,
            )
        }

        viewModelScope.launch {
            val outcome = try {
                withTimeout(RESET_TIMEOUT_MS) {
                    authRepository.resetPassword(
                        username = username,
                        reference = reference,
                        newPassword = newPassword,
                    )
                }
            } catch (timeout: TimeoutCancellationException) {
                null
            }

            when (outcome) {
                is NetworkResult.Success -> _uiState.update {
                    it.copy(
                        isSubmitting = false,
                        // Clear the sensitive new password; keep username/reference
                        // visible alongside the confirmation.
                        newPassword = "",
                        errorMessage = null,
                        successMessage = RESET_SUCCESS_MESSAGE,
                    )
                }
                // Backend error → show its message and retain all inputs (R3.4).
                is NetworkResult.Error -> _uiState.update {
                    it.copy(isSubmitting = false, errorMessage = outcome.message, successMessage = null)
                }
                // 30s timeout (null) or defensive Empty/Loading → retained-input error (R3.4).
                else -> _uiState.update {
                    it.copy(isSubmitting = false, errorMessage = RESET_FAILURE_MESSAGE, successMessage = null)
                }
            }
        }
    }

    private companion object {
        const val PASSWORD_MIN = 8
        const val PASSWORD_MAX = 128

        /** Functional 30s bound on the reset request (R3.4). */
        const val RESET_TIMEOUT_MS = 30_000L

        const val USERNAME_REQUIRED_MESSAGE = "Enter your username."
        const val REFERENCE_REQUIRED_MESSAGE = "Enter your reference."
        const val RESET_SUCCESS_MESSAGE = "Your password was reset. You can now sign in."
        const val RESET_FAILURE_MESSAGE =
            "Couldn't reset your password. Please try again."
    }
}
