package com.teleautomation.android.ui.nav

import com.teleautomation.android.core.AccessDecision
import com.teleautomation.android.core.Module
import com.teleautomation.android.core.RoleModuleAccess
import com.teleautomation.android.data.api.Role
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.types.shouldBeInstanceOf

/**
 * Example-based unit tests for the route-level navigation guard [guardRoute] (R4.4).
 *
 * These verify the deep-link boundary the navigation shell relies on: a Handler
 * targeting an Admin-only route is redirected to the Handler Kit with an
 * authorization error, while allowed and unknown routes pass through. The Compose
 * wiring (that the redirect actually fires and the restricted body is never shown)
 * is covered by the navigation UI tests (tasks plan 7.7).
 */
class NavGuardTest : StringSpec({

    "handler deep-linking to an Admin-only route is redirected to Inbox with an authorization error" {
        // Every Admin-only module route must be blocked for a Handler.
        RoleModuleAccess.ADMIN_ONLY_MODULES.forEach { adminModule ->
            val route = NavModule.forModule(adminModule).route
            val decision = guardRoute(Role.HANDLER, route)
            val redirect = decision.shouldBeInstanceOf<AccessDecision.RedirectWithError>()
            redirect.destination shouldBe Module.Inbox
            redirect.authorizationError.isNotBlank() shouldBe true
        }
    }

    "handler reaching one of its own routes is allowed" {
        RoleModuleAccess.HANDLER_MODULES.forEach { module ->
            val route = NavModule.forModule(module).route
            guardRoute(Role.HANDLER, route) shouldBe AccessDecision.Allowed
        }
    }

    "admin may reach every module route" {
        Module.entries.forEach { module ->
            val route = NavModule.forModule(module).route
            guardRoute(Role.ADMIN, route) shouldBe AccessDecision.Allowed
        }
    }

    "a null route maps to no restricted module and is allowed" {
        guardRoute(Role.HANDLER, null) shouldBe AccessDecision.Allowed
    }

    "an unknown route maps to no restricted module and is allowed" {
        guardRoute(Role.HANDLER, "totally-unknown-route") shouldBe AccessDecision.Allowed
    }
})
