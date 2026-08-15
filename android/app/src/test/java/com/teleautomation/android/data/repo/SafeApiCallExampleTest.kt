package com.teleautomation.android.data.repo

import com.teleautomation.android.core.ConnectivityChecker
import com.teleautomation.android.core.ErrorKind
import com.teleautomation.android.core.NetworkResult
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.types.shouldBeInstanceOf
import kotlinx.coroutines.test.runTest
import java.net.SocketTimeoutException

/**
 * Example-based unit tests for [safeApiCall] (R23.4, R25, R26).
 *
 * Exercise the connectivity gate, success/empty mapping, exception classification,
 * and that the attached retry closure re-issues the same operation (R26.5, R26.6).
 */
class SafeApiCallExampleTest : StringSpec({

    val online = ConnectivityChecker { true }
    val offline = ConnectivityChecker { false }

    "offline aborts without invoking the call and returns Offline" {
        runTest {
            var invoked = false
            val result = safeApiCall(offline, call = {
                invoked = true
                "data"
            })
            invoked shouldBe false
            result.shouldBeInstanceOf<NetworkResult.Error<String>>().kind shouldBe ErrorKind.Offline
        }
    }

    "successful call yields Success" {
        runTest {
            val result = safeApiCall(online, call = { "payload" })
            result.shouldBeInstanceOf<NetworkResult.Success<String>>().data shouldBe "payload"
        }
    }

    "empty payload yields Empty" {
        runTest {
            val result = safeApiCall(online, isEmpty = { it.isEmpty() }, call = { emptyList<String>() })
            result.shouldBeInstanceOf<NetworkResult.Empty>()
        }
    }

    "timeout exception maps to Timeout" {
        runTest {
            val result = safeApiCall<String>(online, call = { throw SocketTimeoutException("late") })
            result.shouldBeInstanceOf<NetworkResult.Error<String>>().kind shouldBe ErrorKind.Timeout
        }
    }

    "unclassified exception maps to Unknown" {
        runTest {
            val result = safeApiCall<String>(online, call = { throw IllegalStateException("boom") })
            result.shouldBeInstanceOf<NetworkResult.Error<String>>().kind shouldBe ErrorKind.Unknown
        }
    }

    "retry closure re-issues the same operation with original parameters" {
        runTest {
            var attempts = 0
            // The call closes over its parameter `id`; retry must re-issue with the same id.
            val id = 42
            suspend fun load(): NetworkResult<String> = safeApiCall(online, call = {
                attempts++
                if (attempts == 1) throw SocketTimeoutException("first attempt times out")
                "loaded-$id"
            })

            val first = load()
            val error = first.shouldBeInstanceOf<NetworkResult.Error<String>>()
            error.kind shouldBe ErrorKind.Timeout

            val retried = error.retry()
            retried.shouldBeInstanceOf<NetworkResult.Success<String>>().data shouldBe "loaded-42"
            attempts shouldBe 2
        }
    }
})
