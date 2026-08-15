package com.teleautomation.android.core

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.nulls.shouldBeNull
import io.kotest.matchers.shouldBe

/**
 * Example-based unit tests for the fleet-action HTTP 403 handling helpers (R4.6).
 *
 * Verify that a forbidden (403) failure is distinguished from every other outcome —
 * including a non-403 [ErrorKind.Client4xx] — and is mapped to a single authorization
 * signal, while success/empty/loading and non-forbidden errors produce no signal so
 * the caller never treats them as a permitted/successful outcome.
 */
class FleetActionAuthorizationTest : StringSpec({

    fun errorWith(status: Int?): NetworkResult<String> =
        NetworkResult.Error(
            kind = NetworkErrorClassifier.classify(isConnected = true, isTimeout = false, httpStatus = status),
            message = "boom",
            retry = { NetworkResult.Empty },
            httpStatus = status,
        )

    // ── Classifier predicate ──
    "isForbidden is true only for exactly 403" {
        NetworkErrorClassifier.isForbidden(403) shouldBe true
        NetworkErrorClassifier.isForbidden(401) shouldBe false
        NetworkErrorClassifier.isForbidden(400) shouldBe false
        NetworkErrorClassifier.isForbidden(404) shouldBe false
        NetworkErrorClassifier.isForbidden(500) shouldBe false
        NetworkErrorClassifier.isForbidden(null) shouldBe false
    }

    // ── A 403 stays in the Client4xx view bucket but is recoverable as forbidden ──
    "a 403 error is classified Client4xx yet detected as forbidden" {
        val result = errorWith(403)
        (result as NetworkResult.Error).kind shouldBe ErrorKind.Client4xx
        result.isForbidden() shouldBe true
        result.forbiddenAuthorizationError() shouldBe FleetActionAuthorization.MESSAGE
        result.forbiddenAuthorizationSignal() shouldBe FleetActionAuthorization.authorizationSignal
    }

    // ── Other 4xx are NOT forbidden ──
    "a non-403 Client4xx error is not forbidden and yields no authorization signal" {
        val result = errorWith(404)
        (result as NetworkResult.Error).kind shouldBe ErrorKind.Client4xx
        result.isForbidden() shouldBe false
        result.forbiddenAuthorizationError().shouldBeNull()
        result.forbiddenAuthorizationSignal().shouldBeNull()
    }

    "a 401 unauthorized error is not forbidden" {
        val result = errorWith(401)
        (result as NetworkResult.Error).kind shouldBe ErrorKind.Unauthorized
        result.isForbidden() shouldBe false
        result.forbiddenAuthorizationError().shouldBeNull()
    }

    // ── Non-error outcomes never imply an authorization signal ──
    "success, empty, and loading are never forbidden" {
        NetworkResult.Success("ok").isForbidden() shouldBe false
        NetworkResult.Success("ok").forbiddenAuthorizationError().shouldBeNull()
        NetworkResult.Empty.isForbidden() shouldBe false
        NetworkResult.Empty.forbiddenAuthorizationError().shouldBeNull()
        NetworkResult.Loading.isForbidden() shouldBe false
        NetworkResult.Loading.forbiddenAuthorizationError().shouldBeNull()
    }

    "an error with no HTTP status (offline/timeout) is not forbidden" {
        val offline = NetworkResult.Error<String>(
            kind = ErrorKind.Offline,
            message = "no network",
            retry = { NetworkResult.Empty },
        )
        offline.isForbidden() shouldBe false
        offline.forbiddenAuthorizationError().shouldBeNull()
    }
})
