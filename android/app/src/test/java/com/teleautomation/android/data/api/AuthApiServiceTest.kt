package com.teleautomation.android.data.api

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.string.shouldContain
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import retrofit2.HttpException
import retrofit2.Retrofit

/**
 * Example-based unit tests for [AuthApiService] DTO/route mapping.
 *
 * Drives the service against a [MockWebServer] using the same lenient
 * kotlinx-serialization converter the app configures, verifying that:
 *  - response DTOs decode the exact Backend JSON shapes (verified against
 *    `core/dashboard_auth_api.py`), including [Role] token mapping and tolerance
 *    of missing/unknown keys (R22.3);
 *  - request DTOs serialize with the Backend's snake_case field names;
 *  - each function targets the correct relative path and method (R23.2);
 *  - a 401 surfaces as an [HttpException] so the repository can classify it as
 *    Unauthorized (R1.8, R2.6).
 */
class AuthApiServiceTest : StringSpec({

    val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        coerceInputValues = true
        explicitNulls = false
    }

    fun serviceFor(server: MockWebServer): AuthApiService =
        Retrofit.Builder()
            .baseUrl(server.url("/"))
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(AuthApiService::class.java)

    "status decodes the full auth-status payload and maps the role" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(
                    MockResponse().setBody(
                        """{"enabled":true,"authenticated":true,"username":"alice","role":"handler","reference":"ref-7"}""",
                    ),
                )
                val status = serviceFor(server).status()

                status shouldBe AuthStatus(
                    enabled = true,
                    authenticated = true,
                    username = "alice",
                    role = Role.HANDLER,
                    reference = "ref-7",
                )
                val recorded = server.takeRequest()
                recorded.method shouldBe "GET"
                recorded.path shouldBe "/auth/status"
            } finally {
                server.shutdown()
            }
        }
    }

    "status tolerates an unknown role and missing keys, defaulting to ADMIN" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(
                    MockResponse().setBody(
                        """{"enabled":true,"authenticated":true,"role":"superuser","extra":"ignored"}""",
                    ),
                )
                val status = serviceFor(server).status()

                status.role shouldBe Role.ADMIN
                status.username shouldBe null
                status.reference shouldBe null
            } finally {
                server.shutdown()
            }
        }
    }

    "login sends username/password and decodes the success body" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(
                    MockResponse().setBody(
                        """{"status":"ok","username":"bob","role":"admin","reference":null}""",
                    ),
                )
                val response = serviceFor(server).login(LoginRequest(username = "bob", password = "s3cret"))

                response.status shouldBe "ok"
                response.username shouldBe "bob"
                response.role shouldBe Role.ADMIN

                val recorded = server.takeRequest()
                recorded.method shouldBe "POST"
                recorded.path shouldBe "/auth/login"
                val sentBody = recorded.body.readUtf8()
                sentBody shouldContain "\"username\":\"bob\""
                sentBody shouldContain "\"password\":\"s3cret\""
            } finally {
                server.shutdown()
            }
        }
    }

    "login surfaces a 401 as an HttpException" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(
                    MockResponse().setResponseCode(401)
                        .setBody("""{"detail":"Invalid username or password"}"""),
                )
                val service = serviceFor(server)

                val thrown = runCatching {
                    service.login(LoginRequest(username = "x", password = "y"))
                }.exceptionOrNull()

                (thrown is HttpException) shouldBe true
                (thrown as HttpException).code() shouldBe 401
            } finally {
                server.shutdown()
            }
        }
    }

    "changePassword serializes snake_case field names" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setBody("""{"status":"ok"}"""))
                val response = serviceFor(server).changePassword(
                    ChangePasswordRequest(currentPassword = "oldpass12", newPassword = "newpass34"),
                )

                response.status shouldBe "ok"
                val recorded = server.takeRequest()
                recorded.method shouldBe "POST"
                recorded.path shouldBe "/auth/change-password"
                val sentBody = recorded.body.readUtf8()
                sentBody shouldContain "\"current_password\":\"oldpass12\""
                sentBody shouldContain "\"new_password\":\"newpass34\""
            } finally {
                server.shutdown()
            }
        }
    }

    "resetPassword serializes username, reference, and snake_case new_password" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setBody("""{"status":"ok"}"""))
                val response = serviceFor(server).resetPassword(
                    username = "carol",
                    reference = "Dave",
                    newPassword = "freshpass1",
                )

                response.status shouldBe "ok"
                val recorded = server.takeRequest()
                recorded.method shouldBe "POST"
                recorded.path shouldBe "/auth/reset-password"
                val sentBody = recorded.body.readUtf8()
                sentBody shouldContain "\"username\":\"carol\""
                sentBody shouldContain "\"reference\":\"Dave\""
                sentBody shouldContain "\"new_password\":\"freshpass1\""
            } finally {
                server.shutdown()
            }
        }
    }

    "logout posts to the logout path and decodes status" {
        runTest {
            val server = MockWebServer().apply { start() }
            try {
                server.enqueue(MockResponse().setBody("""{"status":"ok"}"""))
                val response = serviceFor(server).logout()

                response.status shouldBe "ok"
                val recorded = server.takeRequest()
                recorded.method shouldBe "POST"
                recorded.path shouldBe "/auth/logout"
            } finally {
                server.shutdown()
            }
        }
    }
})
