package com.teleautomation.android.core

import io.kotest.assertions.throwables.shouldThrow
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.types.shouldBeInstanceOf

/**
 * Example-based unit tests for [BoundedLengthPolicy] (R3.5, R7.5, R7.6).
 *
 * These cover concrete accepted/rejected boundary cases for the change-password
 * `[8,128]` and display-name `[1,64]` bounds, plus the trimming policy and
 * misconfigured-bound guards. The exhaustive, generator-driven property coverage
 * for Property 2 is added separately (tasks plan 6.5) and is not duplicated here.
 */
class BoundedLengthExampleTest : StringSpec({

    // ── Change-password bounds [8,128], whitespace-significant (PRESERVE) ──

    "accepts a password at the lower bound of 8" {
        BoundedLengthPolicy.validate("12345678", min = 8, max = 128)
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    "accepts a password at the upper bound of 128" {
        BoundedLengthPolicy.validate("a".repeat(128), min = 8, max = 128)
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    "rejects a password one short of the lower bound as too short" {
        val result = BoundedLengthPolicy.validate("1234567", min = 8, max = 128)
        result.shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe true
    }

    "rejects a password one over the upper bound as too long" {
        val result = BoundedLengthPolicy.validate("a".repeat(129), min = 8, max = 128)
        result.shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe false
    }

    "counts surrounding whitespace in a password under the default PRESERVE policy" {
        // 6 spaces + "12" = length 8, which is at the lower bound when preserved.
        BoundedLengthPolicy.validate("      12", min = 8, max = 128)
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    // ── Display-name bounds [1,64], whitespace-cosmetic (TRIM) ──

    "accepts a display name at the lower bound of 1" {
        BoundedLengthPolicy.validate("A", min = 1, max = 64, trim = BoundedLengthPolicy.TrimPolicy.TRIM)
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    "accepts a display name at the upper bound of 64" {
        BoundedLengthPolicy.validate("n".repeat(64), min = 1, max = 64, trim = BoundedLengthPolicy.TrimPolicy.TRIM)
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    "rejects an empty display name as too short" {
        val result = BoundedLengthPolicy.validate("", min = 1, max = 64, trim = BoundedLengthPolicy.TrimPolicy.TRIM)
        result.shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe true
    }

    "rejects a whitespace-only display name as too short under TRIM" {
        val result = BoundedLengthPolicy.validate("    ", min = 1, max = 64, trim = BoundedLengthPolicy.TrimPolicy.TRIM)
        result.shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe true
    }

    "rejects a display name over 64 characters as too long" {
        val result = BoundedLengthPolicy.validate("n".repeat(65), min = 1, max = 64, trim = BoundedLengthPolicy.TrimPolicy.TRIM)
        result.shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe false
    }

    // ── Misconfigured bounds are programming errors ──

    "throws when min is negative" {
        shouldThrow<IllegalArgumentException> {
            BoundedLengthPolicy.validate("x", min = -1, max = 10)
        }
    }

    "throws when max is less than min" {
        shouldThrow<IllegalArgumentException> {
            BoundedLengthPolicy.validate("x", min = 10, max = 5)
        }
    }
})
