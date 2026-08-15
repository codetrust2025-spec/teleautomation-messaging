package com.teleautomation.android.core

import io.kotest.assertions.throwables.shouldThrow
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe

/**
 * Example-based unit tests for [UnreadBadgeFormatter] (R5.6–R5.8, R11.1).
 *
 * These cover concrete boundary points for both display caps. The exhaustive,
 * generator-driven coverage for Property 5 is added separately (tasks plan 7.4)
 * and is not duplicated here.
 */
class UnreadBadgeFormatterExampleTest : StringSpec({

    // ── Zero → no badge (R5.8) ──
    "zero count yields no badge for any cap" {
        UnreadBadgeFormatter.forNavInbox(0) shouldBe BadgeDisplay.None
        UnreadBadgeFormatter.forConversation(0) shouldBe BadgeDisplay.None
    }

    // ── Nav Inbox cap 99 (R5.6, R5.7) ──
    "nav inbox shows the exact count from 1 up to the cap" {
        UnreadBadgeFormatter.forNavInbox(1) shouldBe BadgeDisplay.Text("1")
        UnreadBadgeFormatter.forNavInbox(42) shouldBe BadgeDisplay.Text("42")
        UnreadBadgeFormatter.forNavInbox(99) shouldBe BadgeDisplay.Text("99")
    }

    "nav inbox shows 99+ above the cap" {
        UnreadBadgeFormatter.forNavInbox(100) shouldBe BadgeDisplay.Text("99+")
        UnreadBadgeFormatter.forNavInbox(5_000) shouldBe BadgeDisplay.Text("99+")
        UnreadBadgeFormatter.forNavInbox(Int.MAX_VALUE) shouldBe BadgeDisplay.Text("99+")
    }

    // ── Per-conversation cap 9999 (R11.1) ──
    "conversation shows the exact count from 1 up to the cap" {
        UnreadBadgeFormatter.forConversation(1) shouldBe BadgeDisplay.Text("1")
        UnreadBadgeFormatter.forConversation(9_999) shouldBe BadgeDisplay.Text("9999")
    }

    "conversation shows 9999+ above the cap" {
        UnreadBadgeFormatter.forConversation(10_000) shouldBe BadgeDisplay.Text("9999+")
        UnreadBadgeFormatter.forConversation(Int.MAX_VALUE) shouldBe BadgeDisplay.Text("9999+")
    }

    // ── Caps are independent of one another ──
    "a count between the two caps is exact for the conversation cap but capped for nav" {
        UnreadBadgeFormatter.format(count = 500, cap = UnreadBadgeFormatter.NAV_INBOX_CAP) shouldBe
            BadgeDisplay.Text("99+")
        UnreadBadgeFormatter.format(count = 500, cap = UnreadBadgeFormatter.CONVERSATION_UNREAD_CAP) shouldBe
            BadgeDisplay.Text("500")
    }

    // ── Precondition guards ──
    "negative count is rejected" {
        shouldThrow<IllegalArgumentException> { UnreadBadgeFormatter.format(count = -1, cap = 99) }
    }

    "non-positive cap is rejected" {
        shouldThrow<IllegalArgumentException> { UnreadBadgeFormatter.format(count = 5, cap = 0) }
    }
})
