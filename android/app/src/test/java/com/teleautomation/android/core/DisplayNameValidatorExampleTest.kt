package com.teleautomation.android.core

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.types.shouldBeInstanceOf

/**
 * Example-based unit tests for [DisplayNameValidator] (R7.5, R7.6).
 *
 * These confirm the named wrapper pins the display-name bounds `[1,64]` and the
 * trimming policy correctly: accepting in-range names, rejecting empty,
 * whitespace-only, and over-length names so the Backend display-name endpoint is
 * never called for an invalid value. The exhaustive, generator-driven property
 * coverage for Property 2 over `[1,64]` is added separately (tasks plan 6.5) and is
 * not duplicated here.
 */
class DisplayNameValidatorExampleTest : StringSpec({

    "exposes the display-name bounds as [1,64]" {
        DisplayNameValidator.MIN_LENGTH shouldBe 1
        DisplayNameValidator.MAX_LENGTH shouldBe 64
    }

    // ── Accepted: 1..64 trimmed ──

    "accepts a single-character display name at the lower bound" {
        DisplayNameValidator.validate("A")
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    "accepts a display name at the upper bound of 64" {
        DisplayNameValidator.validate("n".repeat(64))
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    "accepts a padded name whose trimmed length is within bounds" {
        // Surrounding whitespace is cosmetic; the trimmed content "Ops Lead" is 8 chars.
        DisplayNameValidator.validate("   Ops Lead   ")
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    "accepts a 64-character name surrounded by whitespace because TRIM measures the content" {
        DisplayNameValidator.validate("  " + "n".repeat(64) + "  ")
            .shouldBeInstanceOf<BoundedLengthResult.Accepted>()
    }

    // ── Rejected: empty / whitespace-only → too short ──

    "rejects an empty display name as too short" {
        DisplayNameValidator.validate("")
            .shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe true
    }

    "rejects a whitespace-only display name as too short" {
        DisplayNameValidator.validate("    ")
            .shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe true
    }

    // ── Rejected: over-length → too long ──

    "rejects a display name one over the upper bound as too long" {
        DisplayNameValidator.validate("n".repeat(65))
            .shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe false
    }

    "rejects an over-length name even after trimming surrounding whitespace" {
        DisplayNameValidator.validate("  " + "n".repeat(65) + "  ")
            .shouldBeInstanceOf<BoundedLengthResult.Rejected>().tooShort shouldBe false
    }
})
