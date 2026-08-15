package com.teleautomation.android.core

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContainExactly
import io.kotest.matchers.shouldBe
import io.kotest.matchers.types.shouldBeInstanceOf

/**
 * Example-based unit tests for [LoginInputValidator] (R1.10).
 *
 * These cover concrete points of the login gate: both-present, each-empty, the
 * whitespace-only cases, and the submission shape (trimmed username, raw password).
 * The exhaustive, generator-driven coverage for Property 1 is added separately
 * (tasks plan 6.3) and is not duplicated here.
 */
class LoginInputValidatorExampleTest : StringSpec({

    // ── Both fields present → Valid, login may proceed ──
    "non-empty username and password are accepted" {
        val result = LoginInputValidator.validate("admin", "s3cret")
        result shouldBe LoginValidationResult.Valid(username = "admin", password = "s3cret")
    }

    "username is submitted trimmed while password is preserved exactly" {
        val result = LoginInputValidator.validate("  admin  ", "  pad word  ")
        result shouldBe LoginValidationResult.Valid(username = "admin", password = "  pad word  ")
    }

    // ── Empty / whitespace-only fields → Invalid, offending field identified ──
    "empty username is flagged" {
        val result = LoginInputValidator.validate("", "s3cret")
        result.shouldBeInstanceOf<LoginValidationResult.Invalid>()
            .emptyFields shouldContainExactly setOf(LoginField.USERNAME)
    }

    "empty password is flagged" {
        val result = LoginInputValidator.validate("admin", "")
        result.shouldBeInstanceOf<LoginValidationResult.Invalid>()
            .emptyFields shouldContainExactly setOf(LoginField.PASSWORD)
    }

    "whitespace-only fields are treated as empty" {
        val result = LoginInputValidator.validate("   ", "\t\n ")
        result.shouldBeInstanceOf<LoginValidationResult.Invalid>()
            .emptyFields shouldContainExactly setOf(LoginField.USERNAME, LoginField.PASSWORD)
    }
})
