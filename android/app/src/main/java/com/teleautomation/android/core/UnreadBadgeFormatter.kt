package com.teleautomation.android.core

/**
 * The rendered form of an unread-count badge.
 *
 * This deliberately distinguishes the *absence* of a badge ([None]) from a badge
 * that carries a string value ([Text]) so callers cannot confuse "no badge" with
 * an empty/zero label (R5.8). The Compose layer renders [None] as nothing and
 * [Text] as the supplied label.
 */
sealed interface BadgeDisplay {

    /** No badge is shown (the count is zero). */
    data object None : BadgeDisplay

    /** A badge showing the given [value] label (e.g. `"7"` or `"99+"`). */
    data class Text(val value: String) : BadgeDisplay
}

/**
 * Pure, device-independent unread-count badge formatter shared by the navigation
 * Inbox badge (R5.6–R5.8) and the per-conversation unread display (R11.1).
 *
 * This logic lives in `core` (no Android, Compose, or Retrofit dependencies) so it
 * is unit/property testable on the plain JVM; the `NavScaffold` Inbox badge (tasks
 * plan 7.5) and the inbox/conversation screens (tasks plan 15.x) delegate here so
 * the capping rule has a single source of truth. See the "Presentation Components"
 * section of the design document.
 *
 * Backing requirements:
 *  - R5.6: 1..99 unread on the nav Inbox badge → the exact count.
 *  - R5.7: more than 99 unread → `"99+"`.
 *  - R5.8: zero unread → no badge.
 *  - R11.1: per-conversation unread uses the same rule with a cap of 9999.
 *
 * Backing property (Property 5): for any non-negative `count` and any positive
 * display `cap`, the badge is [BadgeDisplay.None] when `count == 0`, the exact
 * number when `count` is in `1..cap`, and `"{cap}+"` when `count > cap`.
 */
object UnreadBadgeFormatter {

    /** Display cap for the navigation Inbox badge (R5.6, R5.7). */
    const val NAV_INBOX_CAP: Int = 99

    /** Display cap for the per-conversation unread display (R11.1). */
    const val CONVERSATION_UNREAD_CAP: Int = 9_999

    /**
     * Formats [count] into a [BadgeDisplay] under the given display [cap]:
     *  - `count == 0` → [BadgeDisplay.None] (no badge, R5.8).
     *  - `count in 1..cap` → [BadgeDisplay.Text] of the exact number (R5.6, R11.1).
     *  - `count > cap` → [BadgeDisplay.Text] of `"{cap}+"` (R5.7).
     *
     * @param count the non-negative unread count; must be `>= 0`.
     * @param cap the positive display cap above which the `"{cap}+"` form is used.
     * @throws IllegalArgumentException if [count] is negative or [cap] is not positive.
     */
    fun format(count: Int, cap: Int): BadgeDisplay {
        require(count >= 0) { "Unread count must be >= 0, was $count." }
        require(cap >= 1) { "Display cap must be >= 1, was $cap." }

        return when {
            count == 0 -> BadgeDisplay.None
            count <= cap -> BadgeDisplay.Text(count.toString())
            else -> BadgeDisplay.Text("$cap+")
        }
    }

    /** Convenience for the navigation Inbox badge using [NAV_INBOX_CAP] (R5.6–R5.8). */
    fun forNavInbox(count: Int): BadgeDisplay = format(count, NAV_INBOX_CAP)

    /** Convenience for the per-conversation unread display using [CONVERSATION_UNREAD_CAP] (R11.1). */
    fun forConversation(count: Int): BadgeDisplay = format(count, CONVERSATION_UNREAD_CAP)
}
