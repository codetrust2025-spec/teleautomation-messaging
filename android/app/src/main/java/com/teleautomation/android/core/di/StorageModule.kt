package com.teleautomation.android.core.di

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.preferencesDataStoreFile
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Application-scoped on-device storage bindings.
 *
 * Provides the DataStore Preferences instance that backs non-secret persisted
 * configuration — currently the validated Backend base URL owned by
 * [com.teleautomation.android.data.repo.BackendConfigRepository] (R23.6).
 *
 * The session cookie and stored identity (username, role, reference) are held in
 * `EncryptedSharedPreferences` (AES-256, Keystore master key) via
 * [com.teleautomation.android.data.local.SessionStore], which Hilt constructs
 * directly through its `@Inject` constructor.
 *
 * No secret is ever persisted in plaintext; all credential storage is encrypted
 * (R23.3).
 */
@Module
@InstallIn(SingletonComponent::class)
object StorageModule {

    /** Non-secret app preferences (e.g. the configured Backend base URL). */
    @Provides
    @Singleton
    fun providePreferencesDataStore(
        @ApplicationContext context: Context,
    ): DataStore<Preferences> =
        PreferenceDataStoreFactory.create {
            context.preferencesDataStoreFile(PREFERENCES_NAME)
        }

    private const val PREFERENCES_NAME = "teleautomation_prefs"
}
