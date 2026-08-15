package com.teleautomation.android.core

import com.teleautomation.android.data.api.Role

/** Marketing-only top-level modules. Operations screens live on the Operations host. */
enum class Module { Dashboard, Inbox, Accounts, Admin, Logs }

sealed interface AccessDecision {
    data object Allowed : AccessDecision
    data class RedirectWithError(val destination: Module, val authorizationError: String) : AccessDecision
}

object RoleModuleAccess {
    val HANDLER_MODULES: Set<Module> = setOf(Module.Dashboard, Module.Inbox)
    val ADMIN_MODULES: Set<Module> = Module.entries.toSet()
    val ADMIN_ONLY_MODULES: Set<Module> = ADMIN_MODULES - HANDLER_MODULES

    fun navigableModules(role: Role): Set<Module> = when (role) {
        Role.ADMIN -> ADMIN_MODULES
        Role.HANDLER -> HANDLER_MODULES
    }

    fun defaultLanding(role: Role): Module = when (role) {
        Role.ADMIN -> Module.Dashboard
        Role.HANDLER -> Module.Inbox
    }

    fun isAccessAllowed(role: Role, target: Module): Boolean = target in navigableModules(role)

    fun guard(role: Role, target: Module): AccessDecision =
        if (isAccessAllowed(role, target)) AccessDecision.Allowed
        else AccessDecision.RedirectWithError(defaultLanding(role), "${target.name} requires administrator access")
}
