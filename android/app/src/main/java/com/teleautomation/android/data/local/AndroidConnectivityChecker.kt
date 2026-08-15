package com.teleautomation.android.data.local

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.teleautomation.android.core.ConnectivityChecker
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Android implementation of [ConnectivityChecker] backed by [ConnectivityManager]
 * (R26.1). Requires the `ACCESS_NETWORK_STATE` permission, declared in the manifest.
 *
 * The pure offline-classification logic stays in `core`; this class only answers the
 * device-state question that `safeApiCall` consults before transmitting a request.
 */
@Singleton
class AndroidConnectivityChecker @Inject constructor(
    @ApplicationContext private val context: Context,
) : ConnectivityChecker {

    /**
     * @return `true` when an active network reports internet capability, `false`
     *   otherwise (including when no active network exists).
     */
    override fun isConnected(): Boolean {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return false
        val activeNetwork = manager.activeNetwork ?: return false
        val capabilities = manager.getNetworkCapabilities(activeNetwork) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }
}
