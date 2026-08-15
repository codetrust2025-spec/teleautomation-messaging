package com.teleautomation.android.core.di

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import com.teleautomation.android.data.api.AuthInterceptor
import com.teleautomation.android.data.api.DynamicBaseUrlInterceptor
import com.teleautomation.android.data.api.RedactingLoggingInterceptor
import com.teleautomation.android.data.api.UnauthorizedInterceptor
import com.teleautomation.android.data.local.EncryptedCookieJar
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.Converter
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * Application-scoped networking bindings.
 *
 * Provides the real Backend-backed networking stack: a lenient
 * kotlinx-serialization [Json] + matching Retrofit converter, a configured
 * [OkHttpClient] (encrypted cookie jar + auth/401 interceptors + 30s timeouts +
 * secret-redacting logging), and a single base-URL-aware [Retrofit] instance.
 *
 * No mock or fabricated production endpoints are ever contributed here (R23.2);
 * any test doubles live exclusively in the `test` / `androidTest` source sets.
 *
 * ### Base-URL strategy
 *
 * The Backend host is runtime-configurable and may be unset or change while the
 * app runs (`BackendConfigRepository`, R23.6). Retrofit needs a base URL at build
 * time, so a single long-lived Retrofit is built against a fixed placeholder
 * origin ([PLACEHOLDER_BASE_URL]) and a [DynamicBaseUrlInterceptor] rewrites every
 * request's scheme/host/port to the currently-configured Backend just before it
 * is sent. This keeps one stable Retrofit (and one set of cached `ApiService`
 * instances) regardless of host changes; `ApiService` interfaces added in later
 * tasks declare relative paths and are created from this Retrofit unchanged.
 */
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    /** Wall-clock budget applied to connect/read/write and the whole call (R23.5, R26.2). */
    private const val TIMEOUT_SECONDS = 30L

    /**
     * Fixed placeholder origin Retrofit is built against. The real origin is
     * substituted per-request by [DynamicBaseUrlInterceptor]; this value is never
     * actually contacted when a Backend URL is configured.
     */
    private const val PLACEHOLDER_BASE_URL = "http://localhost/"

    /** JSON media type used by the Backend for request/response bodies. */
    private const val JSON_MEDIA_TYPE = "application/json"

    /**
     * Lenient JSON tolerant of unknown keys and malformed payloads, so DTOs keep
     * deserializing as the Backend evolves and arbitrary frames never crash a
     * parse (R22.3). Unknown keys are ignored, relaxed syntax is accepted, and
     * absent values fall back to defaults.
     */
    @Provides
    @Singleton
    fun provideJson(): Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        coerceInputValues = true
        explicitNulls = false
    }

    /** Retrofit converter bridging the lenient [Json] to `application/json` bodies. */
    @Provides
    @Singleton
    fun provideConverterFactory(json: Json): Converter.Factory =
        json.asConverterFactory(JSON_MEDIA_TYPE.toMediaType())

    /**
     * The shared OkHttp client.
     *
     * Interceptor order: the base-URL rewrite runs first so every later stage
     * (and the logger) sees the real target; auth/401 handling next; logging last
     * so it records the final, retargeted request. The encrypted cookie jar
     * attaches/persists the session cookie (R23.3, R2.1). All four timeouts are
     * 30s (R23.5).
     */
    @Provides
    @Singleton
    fun provideOkHttpClient(
        cookieJar: EncryptedCookieJar,
        dynamicBaseUrlInterceptor: DynamicBaseUrlInterceptor,
        authInterceptor: AuthInterceptor,
        unauthorizedInterceptor: UnauthorizedInterceptor,
        loggingInterceptor: RedactingLoggingInterceptor,
    ): OkHttpClient = OkHttpClient.Builder()
        .cookieJar(cookieJar)
        .addInterceptor(dynamicBaseUrlInterceptor)
        .addInterceptor(authInterceptor)
        .addInterceptor(unauthorizedInterceptor)
        .addInterceptor(loggingInterceptor)
        .callTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .writeTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .build()

    /**
     * The single base-URL-aware Retrofit. Built once against [PLACEHOLDER_BASE_URL];
     * the effective origin is supplied per request by [DynamicBaseUrlInterceptor].
     * Later tasks create their `ApiService` interfaces from this instance.
     */
    @Provides
    @Singleton
    fun provideRetrofit(
        okHttpClient: OkHttpClient,
        converterFactory: Converter.Factory,
    ): Retrofit = Retrofit.Builder()
        .baseUrl(PLACEHOLDER_BASE_URL)
        .client(okHttpClient)
        .addConverterFactory(converterFactory)
        .build()
}
