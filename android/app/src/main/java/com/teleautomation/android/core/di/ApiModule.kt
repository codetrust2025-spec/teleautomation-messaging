package com.teleautomation.android.core.di

import com.teleautomation.android.data.api.AccountsApiService
import com.teleautomation.android.data.api.AuthApiService
import com.teleautomation.android.data.api.StateApiService
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import retrofit2.Retrofit
import javax.inject.Singleton

/**
 * Application-scoped bindings for Retrofit `ApiService` interfaces.
 *
 * Each service is created from the single base-URL-aware [Retrofit] provided by
 * [NetworkModule]; the dynamic base-URL interceptor retargets every request to
 * the currently-configured Backend, so these instances remain valid across host
 * changes. No mock or fabricated production endpoints are contributed here
 * (R23.2); test doubles live only in the test source sets.
 *
 * Services for later feature modules are added here as those tasks land.
 */
@Module
@InstallIn(SingletonComponent::class)
object ApiModule {

    /** The `/auth/*` service used by `AuthRepository`. */
    @Provides
    @Singleton
    fun provideAuthApiService(retrofit: Retrofit): AuthApiService =
        retrofit.create(AuthApiService::class.java)

    /** The fleet `/state` + `/start` + `/stop` + `/stats/reset` service used by `StateRepository` (R6). */
    @Provides
    @Singleton
    fun provideStateApiService(retrofit: Retrofit): StateApiService =
        retrofit.create(StateApiService::class.java)

    /** The account/fleet-management service used by `AccountsRepository` (R7). */
    @Provides
    @Singleton
    fun provideAccountsApiService(retrofit: Retrofit): AccountsApiService =
        retrofit.create(AccountsApiService::class.java)
}
