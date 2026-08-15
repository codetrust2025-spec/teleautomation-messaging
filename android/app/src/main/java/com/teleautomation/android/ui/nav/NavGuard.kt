package com.teleautomation.android.ui.nav

import com.teleautomation.android.core.AccessDecision
import com.teleautomation.android.core.RoleModuleAccess
import com.teleautomation.android.data.api.Role

/**
 * Pure navigation-guard resolution at the **route** level (R4.4).
 *
 * [NavScaffold] guards by [com.teleautomation.android.core.Module]; this helper
 * bridges the `NavHost` route string (the unit a tap *or a deep link* targets) to a
 * module and delegates to [RoleModuleAccess.guard], so the same access decision that
 * governs which destinations are presented also governs which destinations may be
 * *shown* — closing the deep-link hole where an Admin-only route could otherwise be
 * reached directly.
 *
 * Resolution:
 *  - A [route] that maps to a known [NavModule] is guarded via
 *    [RoleModuleAccess.guard]; an Admin-only target while [role] is Handler yields
 *    [AccessDecision.RedirectWithError] pointing at the role's default landing (the
 *    Handler Kit) with an authorization error (R4.4).
 *  - A `null` or unknown [route] maps to no module and so cannot be a restricted
 *    target; it resolves to [AccessDecision.Allowed] and the `NavHost` handles the
 *    unknown route normally.
 *
 * Kept free of Compose/Android types so it is unit testable on the plain JVM.
 *
 * @param role the authenticated Operator's role.
 * @param route the `NavHost` route being navigated to (or deep-linked into).
 */
fun guardRoute(role: Role, route: String?): AccessDecision {
    val target = NavModule.forRoute(route)?.module ?: return AccessDecision.Allowed
    return RoleModuleAccess.guard(role, target)
}
