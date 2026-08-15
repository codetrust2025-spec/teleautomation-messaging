/**
 * `data.local` — on-device storage.
 *
 * EncryptedSharedPreferences holds the session cookie + identity and the validated
 * Backend base URL; DataStore holds non-secret preferences. Caches here are
 * display-only and never substituted for a Backend response (R23.1).
 *
 * This file exists to materialize the package directory in the base layout.
 */
package com.teleautomation.android.data.local
