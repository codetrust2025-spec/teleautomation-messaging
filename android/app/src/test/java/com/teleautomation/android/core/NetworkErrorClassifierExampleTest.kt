package com.teleautomation.android.core

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import java.io.InterruptedIOException
import java.net.SocketTimeoutException

/**
 * Example-based unit tests for [NetworkErrorClassifier] (R23.4, R23.5, R26.1–R26.4).
 *
 * These cover concrete points of the design's classification table and the timeout
 * predicate. The exhaustive, generator-driven coverage for Property 31 is added
 * separately (tasks plan 3.4) and is not duplicated here.
 */
class NetworkErrorClassifierExampleTest : StringSpec({

    // ── Connectivity dominates everything ──
    "no connectivity maps to Offline even when a status or timeout is present" {
        NetworkErrorClassifier.classify(isConnected = false, isTimeout = true, httpStatus = 500) shouldBe
            ErrorKind.Offline
        NetworkErrorClassifier.classify(isConnected = false, isTimeout = false, httpStatus = 401) shouldBe
            ErrorKind.Offline
    }

    // ── Timeout outranks HTTP status ──
    "timeout maps to Timeout when connected" {
        NetworkErrorClassifier.classify(isConnected = true, isTimeout = true, httpStatus = null) shouldBe
            ErrorKind.Timeout
        NetworkErrorClassifier.classify(isConnected = true, isTimeout = true, httpStatus = 503) shouldBe
            ErrorKind.Timeout
    }

    // ── HTTP status ranges ──
    "5xx maps to Server5xx" {
        NetworkErrorClassifier.classify(true, false, 500) shouldBe ErrorKind.Server5xx
        NetworkErrorClassifier.classify(true, false, 599) shouldBe ErrorKind.Server5xx
    }

    "401 maps to Unauthorized" {
        NetworkErrorClassifier.classify(true, false, 401) shouldBe ErrorKind.Unauthorized
    }

    "other 4xx maps to Client4xx including 403" {
        NetworkErrorClassifier.classify(true, false, 400) shouldBe ErrorKind.Client4xx
        NetworkErrorClassifier.classify(true, false, 403) shouldBe ErrorKind.Client4xx
        NetworkErrorClassifier.classify(true, false, 404) shouldBe ErrorKind.Client4xx
        NetworkErrorClassifier.classify(true, false, 499) shouldBe ErrorKind.Client4xx
    }

    "no status and no timeout maps to Unknown (parse/other)" {
        NetworkErrorClassifier.classify(true, false, null) shouldBe ErrorKind.Unknown
    }

    "non-error status codes map to Unknown" {
        NetworkErrorClassifier.classify(true, false, 200) shouldBe ErrorKind.Unknown
        NetworkErrorClassifier.classify(true, false, 302) shouldBe ErrorKind.Unknown
    }

    // ── Timeout predicate ──
    "isTimeoutError recognises socket and interrupted IO timeouts" {
        NetworkErrorClassifier.isTimeoutError(SocketTimeoutException("timeout")) shouldBe true
        NetworkErrorClassifier.isTimeoutError(InterruptedIOException("deadline")) shouldBe true
    }

    "isTimeoutError is false for unrelated throwables and null" {
        NetworkErrorClassifier.isTimeoutError(IllegalStateException("boom")) shouldBe false
        NetworkErrorClassifier.isTimeoutError(null) shouldBe false
    }
})
