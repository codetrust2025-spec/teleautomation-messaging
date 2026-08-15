package com.teleautomation.android.core

import io.kotest.assertions.throwables.shouldThrow
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.types.shouldBeInstanceOf

/**
 * Example-based unit tests for [PhoneNumberPolicy] (R8.1, R8.2).
 *
 * These cover concrete accepted/rejected cases: the 4..15 national-digit bounds,
 * empty/malformed inputs, unsupported and longest-prefix country-code selection,
 * normalization, and the misconfigured-set guards. The exhaustive,
 * generator-driven property coverage for Property 9 is added separately (tasks
 * plan 10.5) and is not duplicated here.
 */
class PhoneNumberPolicyExampleTest : StringSpec({

    // ── Accepted: supported country code + 4..15 digits ──

    "accepts a number at the lower bound of 4 national digits" {
        val result = PhoneNumberPolicy.validate("+11234")
        result.shouldBeInstanceOf<PhoneNumberResult.Valid>().normalized shouldBe "+11234"
    }

    "accepts a number at the upper bound of 15 national digits" {
        val result = PhoneNumberPolicy.validate("+91" + "1".repeat(15))
        result.shouldBeInstanceOf<PhoneNumberResult.Valid>().normalized shouldBe "+91" + "1".repeat(15)
    }

    "accepts a typical US number and normalizes it" {
        val result = PhoneNumberPolicy.validate("+14155552671")
        result.shouldBeInstanceOf<PhoneNumberResult.Valid>().normalized shouldBe "+14155552671"
    }

    "trims surrounding whitespace before validating" {
        PhoneNumberPolicy.validate("  +442071838750  ")
            .shouldBeInstanceOf<PhoneNumberResult.Valid>()
    }

    // ── Rejected: empty / malformed ──

    "rejects a blank input" {
        PhoneNumberPolicy.validate("   ")
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    "rejects a number with no leading plus" {
        PhoneNumberPolicy.validate("14155552671")
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    "rejects an unsupported country code" {
        // +999 is not in the default supported set.
        PhoneNumberPolicy.validate("+9991234567")
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    "rejects non-digit characters after the country code" {
        PhoneNumberPolicy.validate("+1415-555-2671")
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    "rejects a country code with no national digits" {
        PhoneNumberPolicy.validate("+1")
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    // ── Rejected: out-of-range digit counts ──

    "rejects 3 national digits as too short" {
        PhoneNumberPolicy.validate("+1123")
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    "rejects 16 national digits as too long" {
        PhoneNumberPolicy.validate("+1" + "2".repeat(16))
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    "rejects a Unicode digit look-alike after the country code" {
        // Arabic-Indic digit U+0661 is not an ASCII digit.
        PhoneNumberPolicy.validate("+1\u0661234567")
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    // ── Longest-prefix country-code selection ──

    "selects the longest matching supported country code" {
        // With both +1 and +12 supported, "+123456" -> code "+12", national "3456".
        val result = PhoneNumberPolicy.validate("+123456", setOf("+1", "+12"))
        result.shouldBeInstanceOf<PhoneNumberResult.Valid>().normalized shouldBe "+123456"
    }

    "honors a caller-restricted supported set" {
        // +44 not in the restricted set -> rejected even though it is a real code.
        PhoneNumberPolicy.validate("+442071838750", setOf("+1", "+91"))
            .shouldBeInstanceOf<PhoneNumberResult.Invalid>()
    }

    // ── Misconfigured supported set is a programming error ──

    "throws when the supported set is empty" {
        shouldThrow<IllegalArgumentException> {
            PhoneNumberPolicy.validate("+11234", emptySet())
        }
    }

    "throws when a supported code is malformed" {
        shouldThrow<IllegalArgumentException> {
            PhoneNumberPolicy.validate("+11234", setOf("1"))
        }
    }
})
