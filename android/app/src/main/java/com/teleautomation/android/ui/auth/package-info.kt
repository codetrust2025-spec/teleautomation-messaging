/**
 * `ui.auth` — Compose screens for the authentication and password-management flows
 * (R1, R2, R3).
 *
 * Hosts the self-service `ForgotPasswordScreen` reached from the login screen's
 * "Forgot password" entry point (R3.1) and the authenticated `ChangePasswordScreen`
 * reached from the settings/profile area (R3.5). Each screen observes immutable
 * state from its ViewModel (`ForgotPasswordViewModel`, `ChangePasswordViewModel`)
 * and forwards user intents, containing no business logic (MVVM).
 */
package com.teleautomation.android.ui.auth
