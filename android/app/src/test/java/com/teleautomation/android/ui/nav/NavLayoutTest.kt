package com.teleautomation.android.ui.nav

import com.teleautomation.android.core.Module
import com.teleautomation.android.data.api.Role
import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContainExactly
import io.kotest.matchers.shouldBe

class NavLayoutTest : StringSpec({
    fun List<NavModule>.modules() = map { it.module }

    "admin navigation contains only Messaging modules" {
        val layout = resolveNavLayout(Role.ADMIN)
        (layout.bottom + layout.drawer).modules() shouldContainExactly listOf(Module.Dashboard, Module.Inbox, Module.Accounts, Module.Admin, Module.Logs)
    }

    "handler navigation contains Messaging dashboard and inbox" {
        val layout = resolveNavLayout(Role.HANDLER)
        layout.bottom.modules() shouldContainExactly listOf(Module.Inbox, Module.Dashboard)
        layout.drawer shouldBe emptyList()
        layout.showMore shouldBe false
    }
})
