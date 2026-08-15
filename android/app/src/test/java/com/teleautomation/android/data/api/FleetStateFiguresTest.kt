package com.teleautomation.android.data.api

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.nulls.shouldBeNull
import io.kotest.matchers.shouldBe

/**
 * Example-based unit tests for the dashboard figures derived from [FleetState]
 * (R6.1, R6.2, R6.3, R6.7) — specifically [FleetState.figuresFor] and the
 * per-account posting-mode resolution that drives the Workspace_Mode filter.
 *
 * The success-rate computation itself is covered exhaustively by Property 6
 * (`SuccessRate`); these tests focus on the aggregation and the mode filtering.
 */
class FleetStateFiguresTest : StringSpec({

    fun account(
        running: Boolean = false,
        success: Int = 0,
        failed: Int = 0,
        nextCycleIn: Int = 0,
        heavyRateLimit: Boolean = false,
        postingMode: String = "campaign",
    ) = AccountWorkerState(
        running = running,
        success = success,
        failed = failed,
        nextCycleIn = nextCycleIn,
        heavyRateLimit = heavyRateLimit,
        postingModeRaw = postingMode,
    )

    // ── FLEET aggregates every account (R6.1, R6.3) ──
    "FLEET figures aggregate all accounts" {
        val state = FleetState(
            accountSlots = listOf("a1", "a2", "a3"),
            accountStates = mapOf(
                "a1" to account(running = true, success = 10, failed = 0, postingMode = "campaign"),
                "a2" to account(running = false, success = 5, failed = 5, nextCycleIn = 30, postingMode = "forwarding"),
                "a3" to account(running = false, success = 0, failed = 0, heavyRateLimit = true, postingMode = "campaign"),
            ),
        )

        val figures = state.figuresFor(WorkspaceMode.FLEET)

        figures.accountCount shouldBe 3
        figures.runningCount shouldBe 1
        figures.restingCount shouldBe 2 // a2 (next cycle) + a3 (heavy rate limit)
        figures.postsSent shouldBe 15
        figures.postsAttempted shouldBe 20
        figures.successRatePct shouldBe 75
        figures.nextCycleRemainingMillis shouldBe 30_000L
    }

    // ── FORWARDING narrows to forwarding accounts (R6.3) ──
    "FORWARDING figures include only forwarding-mode accounts" {
        val state = FleetState(
            accountSlots = listOf("a1", "a2", "a3"),
            accountStates = mapOf(
                "a1" to account(running = true, success = 10, failed = 0, postingMode = "campaign"),
                "a2" to account(running = true, success = 8, failed = 2, nextCycleIn = 45, postingMode = "forwarding"),
                "a3" to account(running = false, success = 4, failed = 0, nextCycleIn = 10, postingMode = "both"),
            ),
        )

        // "both" folds onto FORWARDING (PostingMode.fromBackend), so a2 + a3 are in scope.
        val figures = state.figuresFor(WorkspaceMode.FORWARDING)

        figures.accountCount shouldBe 2
        figures.runningCount shouldBe 1
        figures.postsSent shouldBe 12
        figures.postsAttempted shouldBe 14
        figures.nextCycleRemainingMillis shouldBe 10_000L // min positive across a2/a3
    }

    // ── CAMPAIGN narrows to campaign accounts (R6.3) ──
    "CAMPAIGN figures include only campaign-mode accounts" {
        val state = FleetState(
            accountSlots = listOf("a1", "a2"),
            accountStates = mapOf(
                "a1" to account(running = true, success = 10, failed = 10, postingMode = "campaign"),
                "a2" to account(running = true, success = 8, failed = 2, postingMode = "forwarding"),
            ),
        )

        val figures = state.figuresFor(WorkspaceMode.CAMPAIGN)

        figures.accountCount shouldBe 1
        figures.postsSent shouldBe 10
        figures.postsAttempted shouldBe 20
        figures.successRatePct shouldBe 50
    }

    // ── No account counting down → null countdown (R6.7) ──
    "next-cycle remaining is null when no account is counting down" {
        val state = FleetState(
            accountSlots = listOf("a1"),
            accountStates = mapOf("a1" to account(running = true, nextCycleIn = 0)),
        )

        state.figuresFor(WorkspaceMode.FLEET).nextCycleRemainingMillis.shouldBeNull()
    }

    // ── Empty success rate stays at 0 (R6.1) ──
    "success rate is zero when no posts attempted" {
        val state = FleetState(
            accountSlots = listOf("a1"),
            accountStates = mapOf("a1" to account(success = 0, failed = 0)),
        )

        state.figuresFor(WorkspaceMode.FLEET).successRatePct shouldBe 0
    }

    // ── FLEET account count falls back to the slot list when states are partial ──
    "FLEET account count uses the canonical slot list" {
        val state = FleetState(
            accountSlots = listOf("a1", "a2", "a3", "a4"),
            accountStates = mapOf("a1" to account(running = true)),
        )

        state.figuresFor(WorkspaceMode.FLEET).accountCount shouldBe 4
    }

    // ── Posting-mode resolution folds composite/unknown tokens ──
    "posting mode resolves composite and unknown tokens" {
        account(postingMode = "forwarding").postingMode shouldBe PostingMode.FORWARDING
        account(postingMode = "both").postingMode shouldBe PostingMode.FORWARDING
        account(postingMode = "campaign").postingMode shouldBe PostingMode.CAMPAIGN
        account(postingMode = "none").postingMode shouldBe PostingMode.CAMPAIGN
        account(postingMode = "").postingMode shouldBe PostingMode.CAMPAIGN
    }
})
