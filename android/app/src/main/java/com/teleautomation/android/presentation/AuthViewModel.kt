package com.teleautomation.android.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.teleautomation.android.core.ErrorKind
import com.teleautomation.android.core.LoginField
import com.teleautomation.android.core.LoginInputValidator
import com.teleautomation.android.core.LoginValidationResult
import com.teleautomation.android.core.Module
import com.teleautomation.android.core.NetworkResult
import com.teleautomation.android.core.RoleModuleAccess
import com.teleautomation.android.data.api.AuthEvents
import com.teleautomation.android.data.api.Role
import com.teleautomation.android.data.local.SessionStore
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
 * Immutable auth-gate UI state observed by the navigation host (R1, R2).
 *
 * This is the single source of truth for "is the Operator signed in?" that the
 * single-activity shell switches on: [Loading] renders the splash/auth-gate,
 * [Unauthenticated] renders the login screen (task 6.7), and [Authenticated]
 * renders the role-based shell starting at [Authenticated.landing].
 */
sealed interface AuthUiState {

    /**
     * The startup auth-status check is in flight (R1.1). The shell shows the
     * auth-gate/splash until the Backend responds or the 10s functional bound
     * elapses.
     */
    data object Loading : AuthUiState

    /**
     * No valid [com.teleautomation.android.data.local.SessionStore] session — the
     * login screen is shown (R1.2, R1.5).
     *
     * @property errorMessage a non-null indication shown alongside the login form
     *   when the gate could not confirm the session (auth-status failure or the
     *   10s timeout, R1.4, R2.3); `null` when login is shown for the ordinary
     *   "no session" reason (R1.2).
     */
    data class Unauthenticated(val errorMessage: String? = null) : AuthUiState

    /**
     * A valid session was confirmed/established (R1.3, R1.7, R2.1).
     *
     * @property role the authenticated Operator [Role] reported by the Backend.
     * @property username the Operator username to show in the navigation area
     *   (R2.7); may be `null` when the Backend omits it (e.g. auth disabled).
     * @property landing the role-based default landing module the shell should
     *   show first (R1.3, R2.1), resolved via [RoleModuleAccess.defaultLanding].
     */
    data class Authenticated(
        val role: Role,
        val username: String?,
        val landing: Module,
    ) : AuthUiState
}

/**
 * Transient state of the login form, exposed separately from the [AuthUiState]
 * gate so the login screen (task 6.7) can render field-level feedback without the
 * gate flipping away from [AuthUiState.Unauthenticated] during a failed attempt
 * (R1.8, R1.9, R1.10).
 *
 * @property isSubmitting whether a `POST /auth/login` call is in flight (used to
 *   disable the submit control and avoid duplicate submissions).
 * @property usernameError validation message when the username field is empty
 *   (R1.10); `null` otherwise.
 * @property passwordError validation message when the password field is empty
 *   (R1.10); `null` otherwise.
 * @property errorMessage the Backend authentication error (R1.8) or a connection
 *   failure indication (R1.9) from the last attempt; `null` when there is none.
 * @property passwordClearToken a monotonically increasing one-shot signal: the
 *   screen clears its password field whenever this value changes. Bumped only on
 *   an authentication failure (R1.8); a connection failure leaves entered values
 *   intact for retry (R1.9).
 */
data class LoginFormState(
    val isSubmitting: Boolean = false,
    val usernameError: String? = null,
    val passwordError: String? = null,
    val errorMessage: String? = null,
    val passwordClearToken: Int = 0,
)

/**
 * Presentation-layer ViewModel implementing the **auth-gate**, login, logout, and
 * the global-unauthorized reaction (R1.1–R1.5, R1.7–R1.10, R2.1–R2.3, R2.6, R2.7).
 *
 * Responsibilities:
 *  - **Startup auth-gate**: on construction (and on [retryAuthGate]) it calls
 *    [AuthRepository.status] under a **10s functional timeout** (`withTimeout`) that
 *    sits on top of the 30s OkHttp transport timeout. A valid session restores the
 *    authenticated state at the role's default landing (R1.3, R2.1); no/invalid
 *    session shows login (R1.2) and clears the stored session (R2.2); an auth-status
 *    failure or the 10s timeout shows login with an error indication while
 *    **retaining** any stored session for a subsequent retry (R1.4, R2.3).
 *  - **Global 401**: collects [AuthEvents.unauthorized] (emitted by the OkHttp
 *    `UnauthorizedInterceptor` for any non-login/non-status `401`), clears the
 *    stored session, and routes to login (R2.6).
 *  - **Login**: gates on [LoginInputValidator] first so an empty field never calls
 *    the Backend (R1.10); on success stores the session and moves to
 *    [AuthUiState.Authenticated] (R1.7); on authentication failure surfaces the
 *    Backend error, retains the username, and signals the password to be cleared
 *    (R1.8); on connection failure surfaces a connection error without storing a
 *    session (R1.9).
 *  - **Logout**: delegates to [AuthRepository.logout] (which always clears local
 *    session state) and routes to login (R2.2/R2.4 cleanup is in the repository).
 *
 * The ViewModel performs no navigation itself; it only exposes [uiState] and
 * [loginForm] for the shell/screen to react to (MVVM).
 */
@HiltViewModel
class AuthViewModel @Inject constructor(
    private val authRepository: AuthRepository,
    private val sessionStore: SessionStore,
    private val authEvents: AuthEvents,
) : ViewModel() {

    private val _uiState = MutableStateFlow<AuthUiState>(AuthUiState.Loading)
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    private val _loginForm = MutableStateFlow(LoginFormState())
    val loginForm: StateFlow<LoginFormState> = _loginForm.asStateFlow()

    init {
        observeUnauthorized()
        runAuthGate()
    }

    /**
     * Re-runs the startup auth-status check (R2.3). Intended for the "retry" control
     * shown when the gate timed out or failed while a stored session is still
     * retained.
     */
    fun retryAuthGate() {
        runAuthGate()
    }

    /**
     * Startup auth-gate (R1.1–R1.4, R2.1–R2.3).
     *
     * Sets [AuthUiState.Loading], then resolves the stored session against the
     * Backend under a 10s functional timeout and maps the outcome to the gate state.
     */
    private fun runAuthGate() {
        _uiState.value = AuthUiState.Loading
        viewModelScope.launch {
            when (val outcome = resolveAuthStatus()) {
                is AuthGateOutcome.Authenticated -> {
                    val status = outcome.status
                    _loginForm.value = LoginFormState()
                    _uiState.value = AuthUiState.Authenticated(
                        role = status.role,
                        username = status.username,
                        landing = RoleModuleAccess.defaultLanding(status.role),
                    )
                }
                // No valid session: clear any stale stored session and show login
                // for the ordinary "not signed in" reason (R1.2, R2.2).
                AuthGateOutcome.Invalid -> {
                    sessionStore.clear()
                    _uiState.value = AuthUiState.Unauthenticated()
                }
                // Auth-status failure or 10s timeout: show login with an error, but
                // retain the stored session so the Operator can retry (R1.4, R2.3).
                is AuthGateOutcome.Failure -> {
                    _uiState.value = AuthUiState.Unauthenticated(errorMessage = outcome.message)
                }
            }
        }
    }

    /**
     * Calls `GET /auth/status` under the 10s functional timeout and reduces the
     * result to an [AuthGateOutcome]. The `withTimeout` bound layers the functional
     * 10s requirement (R1.1) on top of the 30s OkHttp transport timeout; when it
     * fires it surfaces as a retained-session failure (R2.3).
     */
    private suspend fun resolveAuthStatus(): AuthGateOutcome =
        try {
            withTimeout(AUTH_STATUS_TIMEOUT_MS) {
                when (val result = authRepository.status()) {
                    is NetworkResult.Success ->
                        if (result.data.authenticated) {
                            AuthGateOutcome.Authenticated(result.data)
                        } else {
                            AuthGateOutcome.Invalid
                        }
                    // A 401 means the stored session is invalid/expired (R2.2).
                    is NetworkResult.Error ->
                        if (result.kind == ErrorKind.Unauthorized) {
                            AuthGateOutcome.Invalid
                        } else {
                            AuthGateOutcome.Failure(result.message)
                        }
                    // status() never reports Empty/Loading; treat defensively as a
                    // non-fatal failure that keeps the stored session for retry.
                    NetworkResult.Empty, NetworkResult.Loading ->
                        AuthGateOutcome.Failure(AUTH_STATUS_FAILURE_MESSAGE)
                }
            }
        } catch (timeout: TimeoutCancellationException) {
            AuthGateOutcome.Failure(AUTH_STATUS_FAILURE_MESSAGE)
        }

    /**
     * Attempts a login (R1.6–R1.10).
     *
     * Validates the entered fields first via [LoginInputValidator]; an empty field
     * is surfaced inline and the Backend is **not** called (R1.10). On a valid
     * submission it calls `POST /auth/login` and maps the result: success →
     * [AuthUiState.Authenticated] (R1.7); an authentication failure (401 / other
     * 4xx) surfaces the Backend error, retains the username, and signals the
     * password to clear (R1.8); any connection-class failure surfaces a connection
     * error and stores no session (R1.9).
     */
    fun login(username: String, password: String) {
        when (val validation = LoginInputValidator.validate(username, password)) {
            is LoginValidationResult.Invalid -> {
                _loginForm.update { current ->
                    current.copy(
                        isSubmitting = false,
                        usernameError = if (LoginField.USERNAME in validation.emptyFields) {
                            USERNAME_REQUIRED_MESSAGE
                        } else {
                            null
                        },
                        passwordError = if (LoginField.PASSWORD in validation.emptyFields) {
                            PASSWORD_REQUIRED_MESSAGE
                        } else {
                            null
                        },
                        errorMessage = null,
                    )
                }
            }

            is LoginValidationResult.Valid -> {
                _loginForm.update {
                    it.copy(
                        isSubmitting = true,
                        usernameError = null,
                        passwordError = null,
                        errorMessage = null,
                    )
                }
                viewModelScope.launch {
                    when (val result = authRepository.login(validation.username, validation.password)) {
                        is NetworkResult.Success -> {
                            val resp = result.data
                            _loginForm.value = LoginFormState()
                            _uiState.value = AuthUiState.Authenticated(
                                role = resp.role,
                                username = resp.username ?: validation.username,
                                landing = RoleModuleAccess.defaultLanding(resp.role),
                            )
                        }
                        is NetworkResult.Error -> handleLoginError(result)
                        // login() never reports Empty/Loading; treat defensively as
                        // a non-fatal connection-style failure with no session stored.
                        NetworkResult.Empty, NetworkResult.Loading -> {
                            _loginForm.update {
                                it.copy(isSubmitting = false, errorMessage = LOGIN_CONNECTION_MESSAGE)
                            }
                        }
                    }
                }
            }
        }
    }

    /**
     * Maps a failed login to the login-form feedback. An authentication failure
     * (`Unauthorized`/`Client4xx`) keeps the username, clears the password, and
     * shows the Backend message (R1.8); any other kind (offline/timeout/5xx/unknown)
     * is treated as a connection failure that retains the entered values for retry
     * and stores no session (R1.9).
     */
    private fun handleLoginError(error: NetworkResult.Error<*>) {
        val isAuthFailure = error.kind == ErrorKind.Unauthorized || error.kind == ErrorKind.Client4xx
        _loginForm.update { current ->
            current.copy(
                isSubmitting = false,
                usernameError = null,
                passwordError = null,
                errorMessage = error.message,
                passwordClearToken = if (isAuthFailure) {
                    current.passwordClearToken + 1
                } else {
                    current.passwordClearToken
                },
            )
        }
    }

    /**
     * Signs the Operator out (R2.2). Delegates to [AuthRepository.logout], which
     * always clears the local session (cookies + identity) regardless of the
     * Backend outcome, then routes to login.
     */
    fun logout() {
        viewModelScope.launch {
            authRepository.logout()
            _loginForm.value = LoginFormState()
            _uiState.value = AuthUiState.Unauthenticated()
        }
    }

    /**
     * Collects the global [AuthEvents.unauthorized] signal — emitted by the OkHttp
     * `UnauthorizedInterceptor` on any non-login/non-status `401` — clears the
     * stored session, and routes to login (R2.6).
     */
    private fun observeUnauthorized() {
        viewModelScope.launch {
            authEvents.unauthorized.collect {
                sessionStore.clear()
                _loginForm.value = LoginFormState()
                _uiState.value = AuthUiState.Unauthenticated()
            }
        }
    }

    /**
     * Internal reduction of the auth-status check used by [runAuthGate]. Kept
     * private so the public surface stays the two state flows plus the intents.
     */
    private sealed interface AuthGateOutcome {
        /** A valid, authenticated session was confirmed. */
        data class Authenticated(val status: com.teleautomation.android.data.api.AuthStatus) :
            AuthGateOutcome

        /** No valid session (not authenticated or `401`): clear and show login. */
        data object Invalid : AuthGateOutcome

        /** Auth-status failure or 10s timeout: show login with [message], retain session. */
        data class Failure(val message: String) : AuthGateOutcome
    }

    private companion object {
        /** Functional 10s bound on the startup auth-status check (R1.1, R2.3). */
        const val AUTH_STATUS_TIMEOUT_MS = 10_000L

        const val AUTH_STATUS_FAILURE_MESSAGE =
            "Couldn't verify your session. Please sign in or try again."
        const val USERNAME_REQUIRED_MESSAGE = "Enter your username."
        const val PASSWORD_REQUIRED_MESSAGE = "Enter your password."
        const val LOGIN_CONNECTION_MESSAGE =
            "Couldn't reach the server. Check your connection and try again."
    }
}
