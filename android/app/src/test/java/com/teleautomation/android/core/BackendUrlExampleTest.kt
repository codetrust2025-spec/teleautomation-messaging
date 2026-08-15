package com.teleautomation.android.core

import io.kotest.assertions.throwables.shouldThrow
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.string.shouldContain
import io.kotest.matchers.types.shouldBeInstanceOf

/**
 * Example-based unit tests for [BackendUrlPolicy] (R23.6).
 *
 * These cover concrete accepted/rejected cases and WebSocket-derivation examples.
 * The exhaustive, generator-driven property coverage for Property 28 is added
 * separately (tasks plan 2.2) and is not duplicated here.
 */
class BackendUrlExampleTest : StringSpec({

    // ── Accepted base URLs ──
    "accepts a plain https URL" {
        val result = BackendUrlPolicy.validate("https://api.example.com")
        result.shouldBeInstanceOf<BackendUrlResult.Valid>().canonical shouldBe "https://api.example.com"
    }

    "accepts an http URL with a port and path" {
        BackendUrlPolicy.validate("http://10.0.2.2:8000/api")
            .shouldBeInstanceOf<BackendUrlResult.Valid>()
    }

    "accepts ws and wss URLs" {
        BackendUrlPolicy.validate("ws://localhost:8000").shouldBeInstanceOf<BackendUrlResult.Valid>()
        BackendUrlPolicy.validate("wss://example.com").shouldBeInstanceOf<BackendUrlResult.Valid>()
    }

    "trims surrounding whitespace before accepting" {
        val result = BackendUrlPolicy.validate("   https://example.com   ")
        result.shouldBeInstanceOf<BackendUrlResult.Valid>().canonical shouldBe "https://example.com"
    }

    // ── Rejected base URLs ──
    "rejects a blank value" {
        BackendUrlPolicy.validate("   ").shouldBeInstanceOf<BackendUrlResult.Invalid>()
    }

    "rejects a javascript scheme" {
        val result = BackendUrlPolicy.validate("javascript:alert('x')")
        result.shouldBeInstanceOf<BackendUrlResult.Invalid>().reason shouldContain "scheme"
    }

    "rejects a file scheme" {
        BackendUrlPolicy.validate("file:///etc/passwd").shouldBeInstanceOf<BackendUrlResult.Invalid>()
    }

    "rejects an http URL with an empty host" {
        BackendUrlPolicy.validate("http://").shouldBeInstanceOf<BackendUrlResult.Invalid>()
    }

    "rejects a value with no scheme" {
        BackendUrlPolicy.validate("example.com/api").shouldBeInstanceOf<BackendUrlResult.Invalid>()
    }

    "rejects a malformed URL" {
        BackendUrlPolicy.validate("http://exa mple.com").shouldBeInstanceOf<BackendUrlResult.Invalid>()
    }

    // ── WebSocket derivation ──
    "derives wss from https preserving host and port and appending /ws" {
        BackendUrlPolicy.deriveWebSocketUrl("https://api.example.com:8443/base") shouldBe
            "wss://api.example.com:8443/ws"
    }

    "derives ws from http without an explicit port" {
        BackendUrlPolicy.deriveWebSocketUrl("http://localhost") shouldBe "ws://localhost/ws"
    }

    "preserves ws and wss schemes" {
        BackendUrlPolicy.deriveWebSocketUrl("ws://localhost:8000") shouldBe "ws://localhost:8000/ws"
        BackendUrlPolicy.deriveWebSocketUrl("wss://example.com") shouldBe "wss://example.com/ws"
    }

    "throws when deriving from a base with an unsupported scheme" {
        shouldThrow<IllegalArgumentException> {
            BackendUrlPolicy.deriveWebSocketUrl("file:///etc/passwd")
        }
    }
})
