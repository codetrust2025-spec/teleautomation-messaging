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
 * Immutable UI state for the authenticated change-password flow (R3.5, R3.6, R3.7).
 *
 * The Backend `POST /auth/change-password` endpoint requires `current_password` and
 * `new_password` (verified against `core/dashboard_auth_api.py`). Each password
 * value must be within `[8,128]` (R3.5), enforced by the shared
 * [BoundedLengthPolicy] validator before any Backend call (Property 2). On success
 * the form is cleared (R3.6); on failure both inputs are retained (R3.7).
 *
 * @property currentPassword the Operator's existing password.
 * @property newPassword the proposed new password.
 * @property currentPasswordError inline validation message when [currentPassword]
 *   is outside `[8,128]`; `null` otherwise.
 * @property newPasswordError inline validation message when [newPassword] is
 *   outside `[8,128]`; `null` otherwise.
 * @property isSubmitting whether a change request is in flight (disables the submit
 *   control and avoids duplicate submissions).
 * @property errorMessage the Backend/connection error from the last attempt (R3.7),
 *   or `null` when there is none.
 * @property successMessage a confirmation shown after a successful change (R3.6), or
 *   `null` when there is nothing to confirm.
 */
data class ChangePasswordUiState(
    val currentPassword: String = "",
    val newPassword: String = "",
    val currentPasswordError: String? = null,
    val newPasswordError: String? = null,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val successMessage: String? = null,
)

/**
 * Presentation-layer ViewModel for
 * [com.teleautomation.android.ui.auth.ChangePasswordScreen] (R3.5, R3.6, R3.7).
 *
 * Holds the change-password form state, validates both password values in the pure
 * logic layer, and delegates the Backend round-trip to
 * [AuthRepository.changePassword]. The screen renders [uiState] and forwards intents
 * ([onCurrentPasswordChanged], [onNewPasswordChanged], [onSubmit]) — it contains no
 * business logic (MVVM).
 *
 * Submission is gated by [BoundedLengthPolicy] for both the current and new password
 * (`[8,128]`, R3.5 / Property 2); if either is invalid the offending field is
 * identified inline and the Backend is **not** called. A valid submission calls
 * `POST /auth/change-password` under a 30s functional bound: a success clears the
 * form and surfaces a confirmation (R3.6), while a Backend rejection or the 30s
 * timeout surfaces an error and retains both inputs for retry (R3.7).
 */
@HiltViewModel
class ChangePasswordViewModel @Inject constructor(
    private val authRepository: AuthRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(ChangePasswordUiState())
    val uiState: StateFlow<ChangePasswordUiState> = _uiState.asStateFlow()

    /** Records the latest current-password text and clears stale messages. */
    fun onCurrentPasswordChanged(value: String) {
        _uiState.update {
            it.copy(
                currentPassword = value,
                currentPasswordError = null,
                errorMessage = null,
                successMessage = null,
            )
        }
    }

    /** Records the latest new-password text and clears stale messages. */
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
     * Validates both password values and, when valid, submits the change request
     * (R3.5, R3.6, R3.7).
     *
     * Identifies every offending field inline and skips the Backend call when either
     * password is outside `[8,128]`. On a valid submission it calls
     * [AuthRepository.changePassword] under a 30s functional bound and maps the
     * outcome to a cleared form + confirmation (R3.6) or a retained-input error
     * (R3.7).
     */
    fun onSubmit() {
        val current = _uiState.value
        val currentPassword = current.currentPassword
        val newPassword = current.newPassword

        val currentPasswordError = validatePassword(currentPassword)
        val newPasswordError = validatePassword(newPassword)

        if (currentPasswordError != null || newPasswordError != null) {
            _uiState.update {
                it.copy(
                    currentPasswordError = currentPasswordError,
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
                currentPasswordError = null,
                newPasswordError = null,
                errorMessage = null,
                successMessage = null,
            )
        }

        viewModelScope.launch {
            val outcome = try {
                withTimeout(CHANGE_TIMEOUT_MS) {
                    authRepository.changePassword(
                        currentPassword = currentPassword,
                        newPassword = newPassword,
                    )
                }
            } catch (timeout: TimeoutCancellationException) {
                null
            }

            when (outcome) {
                // Success → clear the form and show the confirmation (R3.6).
                is NetworkResult.Success -> _uiState.value = ChangePasswordUiState(
                    successMessage = CHANGE_SUCCESS_MESSAGE,
                )
                // Backend rejection → show its message and retain both inputs (R3.7).
                is NetworkResult.Error -> _uiState.update {
                    it.copy(isSubmitting = false, errorMessage = outcome.message, successMessage = null)
                }
                // 30s timeout (null) or defensive Empty/Loading → retained-input error (R3.7).
                else -> _uiState.update {
                    it.copy(isSubmitting = false, errorMessage = CHANGE_FAILURE_MESSAGE, successMessage = null)
                }
            }
        }
    }

    /**
     * Validates a single password value against the `[8,128]` bounds (R3.5). Returns
     * the rejection reason to show inline, or `null` when the value is accepted.
     * Whitespace is significant for secrets, so [BoundedLengthPolicy] is invoked with
     * its default [com.teleautomation.android.core.BoundedLengthPolicy.TrimPolicy.PRESERVE].
     */
    private fun validatePassword(value: String): String? =
        when (val result = BoundedLengthPolicy.validate(value, PASSWORD_MIN, PASSWORD_MAX)) {
            is BoundedLengthResult.Rejected -> result.reason
            BoundedLengthResult.Accepted -> null
        }

    private companion object {
        const val PASSWORD_MIN = 8
        const val PASSWORD_MAX = 128

        /** Functional 30s bound on the change request (R3.7). */
        const val CHANGE_TIMEOUT_MS = 30_000L

        const val CHANGE_SUCCESS_MESSAGE = "Your password was changed."
        const val CHANGE_FAILURE_MESSAGE =
            "Couldn't change your password. Please try again."
    }
}
