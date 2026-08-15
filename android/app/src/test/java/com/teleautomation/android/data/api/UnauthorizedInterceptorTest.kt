package com.teleautomation.android.data.api

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer

/**
 * Unit tests for [UnauthorizedInterceptor] and [AuthInterceptor].
 *
 * Validates the 401 -> AuthEvents.unauthorized signalling contract, the
 * login/auth-status exemptions, and the no-op pass-through behaviour
 * (Requirements 2.6, 23.3, 26.4).
 *
 * [AuthEvents.unauthorized] is a hot, no-replay [kotlinx.coroutines.flow.SharedFlow],
 * so each test subscribes a collector BEFORE issuing the request to deterministically
 * observe (or confirm the absence of) the emission.
 */
class UnauthorizedInterceptorTest : StringSpec({

    fun clientWith(vararg interceptors: Interceptor): OkHttpClient =
        OkHttpClient.Builder().apply {
            interceptors.forEach { addInterceptor(it) }
        }.build()

    "emits unauthorized on 401 for a non-auth path" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setResponseCode(401))
                val authEvents = AuthEvents()
                val client = clientWith(UnauthorizedInterceptor(authEvents))

                var count = 0
                val job = launch(UnconfinedTestDispatcher(testScheduler)) {
                    authEvents.unauthorized.collect { count++ }
                }
                runCurrent()

                val request = Request.Builder().url(server.url("/state")).build()
                client.newCall(request).execute().close()
                runCurrent()

                count shouldBe 1
                job.cancel()
            } finally {
                server.shutdown()
            }
        }
    }

    "does NOT emit on 401 for the login path" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setResponseCode(401))
                val authEvents = AuthEvents()
                val client = clientWith(UnauthorizedInterceptor(authEvents))

                var count = 0
                val job = launch(UnconfinedTestDispatcher(testScheduler)) {
                    authEvents.unauthorized.collect { count++ }
                }
                runCurrent()

                val request = Request.Builder().url(server.url("/auth/login")).build()
                client.newCall(request).execute().close()
                runCurrent()

                count shouldBe 0
                job.cancel()
            } finally {
                server.shutdown()
            }
        }
    }

    "does NOT emit on 401 for the auth-status path" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setResponseCode(401))
                val authEvents = AuthEvents()
                val client = clientWith(UnauthorizedInterceptor(authEvents))

                var count = 0
                val job = launch(UnconfinedTestDispatcher(testScheduler)) {
                    authEvents.unauthorized.collect { count++ }
                }
                runCurrent()

                val request = Request.Builder().url(server.url("/auth/status")).build()
                client.newCall(request).execute().close()
                runCurrent()

                count shouldBe 0
                job.cancel()
            } finally {
                server.shutdown()
            }
        }
    }

    "does NOT emit on a successful (non-401) response" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setResponseCode(200))
                val authEvents = AuthEvents()
                val client = clientWith(UnauthorizedInterceptor(authEvents))

                var count = 0
                val job = launch(UnconfinedTestDispatcher(testScheduler)) {
                    authEvents.unauthorized.collect { count++ }
                }
                runCurrent()

                val request = Request.Builder().url(server.url("/state")).build()
                client.newCall(request).execute().close()
                runCurrent()

                count shouldBe 0
                job.cancel()
            } finally {
                server.shutdown()
            }
        }
    }

    "AuthInterceptor passes the request through unchanged and returns the response" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setResponseCode(200).setBody("ok"))
                val client = clientWith(AuthInterceptor())

                val request = Request.Builder().url(server.url("/state")).build()
                val response = client.newCall(request).execute()
                val code = response.code
                val body = response.body?.string()
                response.close()

                code shouldBe 200
                body shouldBe "ok"
                server.requestCount shouldBe 1
            } finally {
                server.shutdown()
            }
        }
    }
})
