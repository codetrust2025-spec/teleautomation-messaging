package com.teleautomation.android

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * Application entry-point that bootstraps the Hilt dependency graph.
 *
 * Annotating the [Application] with [HiltAndroidApp] generates the application-level
 * Dagger component that all `@AndroidEntryPoint` consumers (Activities, ViewModels,
 * etc.) resolve their bindings from. Concrete bindings are contributed by the
 * `core.di` modules, which later tasks fill with networking and storage providers.
 */
@HiltAndroidApp
class TeleAutomationApp : Application()
