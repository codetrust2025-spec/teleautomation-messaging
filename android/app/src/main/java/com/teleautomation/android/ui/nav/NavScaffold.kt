package com.teleautomation.android.ui.nav

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.teleautomation.android.core.AccessDecision
import com.teleautomation.android.core.AuthorizationSignal
import com.teleautomation.android.core.BadgeDisplay
import com.teleautomation.android.core.Module
import com.teleautomation.android.core.RoleModuleAccess
import com.teleautomation.android.core.UnreadBadgeFormatter
import com.teleautomation.android.core.realtime.ConnectionState
import com.teleautomation.android.data.api.Role
import com.teleautomation.android.ui.accounts.AccountsRoute
import com.teleautomation.android.ui.components.OfflineBanner
import com.teleautomation.android.ui.dashboard.DashboardScreen
import com.teleautomation.android.ui.theme.TeleAutomationTheme
import kotlinx.coroutines.launch

/**
 * Single-activity navigation shell: a role-resolved `NavHost` presented through an
 * Android bottom navigation bar plus an overflow drawer (R5, R24.2).
 *
 * Behaviour:
 *  - **Role-resolved destinations** come from [RoleModuleAccess.navigableModules]
 *    via [resolveNavLayout]: Admin gets Dashboard/Inbox/Accounts/Candidates in the
 *    bottom bar and Daily Ops/Data Room/Admin/Logs behind a "More" drawer; Handler
 *    gets its three destinations entirely in the bottom bar (R4.1, R4.2, R5.1, R5.2).
 *  - The start destination is the role's [RoleModuleAccess.defaultLanding].
 *  - The selected destination is rendered in a visually distinct active state and
 *    its module is shown within the host on selection (R5.3).
 *  - Bottom-bar / drawer navigation pops to the start destination saving state and
 *    restores state on return, so device back returns to the previous screen when a
 *    back-stack entry exists and otherwise exits to the device home without killing
 *    background work — `NavHost` defers unhandled back to the system (R5.4, R5.5).
 *  - The Inbox destination carries the unread badge from
 *    [UnreadBadgeFormatter.forNavInbox] (R5.6–R5.8).
 *  - [OfflineBanner] is wired into the scaffold chrome, bound to [connectionState].
 *  - **Navigation guard (R4.4).** Every route — including a direct deep link — is
 *    guarded via [guardRoute]/[RoleModuleAccess.guard]. A Handler that reaches an
 *    Admin-only route never sees that destination's content: it is redirected to the
 *    Handler Kit (the role default landing) on first composition (well within the 1s
 *    bound) and an authorization error is surfaced through the scaffold snackbar and
 *    the optional [onAuthorizationError] hook.
 *
 * Per-route bodies are [PlaceholderScreen]s for modules whose real screens land in
 * later tasks; those tasks replace the bodies in place. This composable accepts the
 * current [role], the [inboxUnreadCount], and the [connectionState] as inputs so it
 * stays stateless and previewable; a later task supplies them from app state.
 *
 * @param role the authenticated Operator's role driving the visible destinations.
 * @param inboxUnreadCount current Inbox unread count for the nav badge (R5.6–R5.8).
 * @param connectionState realtime connection state driving the [OfflineBanner].
 * @param username the authenticated Operator username shown in the nav area's
 *   account menu (R2.7); `null` when the Backend omitted it (e.g. auth disabled).
 * @param onLogout sign-out hook invoked from the account menu (R2.4).
 * @param modifier applied to the shell container.
 * @param navController the navigation controller (overridable for tests/previews).
 * @param onAuthorizationError invoked with the [AuthorizationSignal] whenever the
 *   guard blocks a restricted destination (R4.4); defaults to a no-op since the
 *   scaffold already surfaces the message via its snackbar.
 * @param onLoginTelegram navigation hook forwarded to the Accounts detail view to
 *   open the Telegram OTP login screen for a slot (R8 / task 10.6); defaults to a
 *   no-op until that screen is wired.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NavScaffold(
    role: Role,
    inboxUnreadCount: Int,
    connectionState: ConnectionState,
    username: String? = null,
    onLogout: () -> Unit = {},
    modifier: Modifier = Modifier,
    navController: NavHostController = rememberNavController(),
    onAuthorizationError: (AuthorizationSignal) -> Unit = {},
    onLoginTelegram: (String) -> Unit = {},
) {
    val layout = remember(role) { resolveNavLayout(role) }
    val startRoute = remember(role) {
        NavModule.forModule(RoleModuleAccess.defaultLanding(role)).route
    }

    val drawerState = androidx.compose.material3.rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    val navigate: (String) -> Unit = { route ->
        navController.navigate(route) {
            // Standard bottom-nav back-stack hygiene: a single instance per
            // top-level destination, with state saved/restored across switches so
            // device back returns to the previous screen (R5.4).
            popUpTo(navController.graph.findStartDestination().id) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }

    // Surfaces an authorization error both on the scaffold snackbar (default UX) and
    // through the optional host/test hook (R4.4).
    val surfaceAuthorizationError: (AuthorizationSignal) -> Unit = { signal ->
        scope.launch { snackbarHostState.showSnackbar(signal.message) }
        onAuthorizationError(signal)
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = layout.drawer.isNotEmpty(),
        modifier = modifier,
        drawerContent = {
            ModalDrawerSheet {
                NavDrawerContent(
                    destinations = layout.drawer,
                    currentRoute = currentRoute,
                    inboxUnreadCount = inboxUnreadCount,
                    onSelect = { dest ->
                        scope.launch { drawerState.close() }
                        navigate(dest.route)
                    },
                )
            }
        },
    ) {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbarHostState) },
            topBar = {
                val title = NavModule.forRoute(currentRoute)?.label ?: "TeleAutomation"
                TopAppBar(
                    title = { Text(title) },
                    navigationIcon = {
                        if (layout.drawer.isNotEmpty()) {
                            IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                Icon(
                                    imageVector = Icons.Filled.Menu,
                                    contentDescription = "Open navigation drawer",
                                )
                            }
                        }
                    },
                    actions = {
                        AccountMenu(username = username, onLogout = onLogout)
                    },
                )
            },
            bottomBar = {
                NavBottomBar(
                    layout = layout,
                    currentRoute = currentRoute,
                    inboxUnreadCount = inboxUnreadCount,
                    onSelect = { navigate(it.route) },
                    onMore = { scope.launch { drawerState.open() } },
                )
            },
        ) { innerPadding ->
            Column(modifier = Modifier.padding(innerPadding)) {
                // Offline indicator wired into the shell chrome (R22.7).
                OfflineBanner(connectionState = connectionState)
                NavHost(
                    navController = navController,
                    startDestination = startRoute,
                    modifier = Modifier.fillMaxSize(),
                ) {
                    // Register every module route — not just the role-resolved ones —
                    // so a direct deep link to a restricted route still resolves and
                    // is intercepted by the guard rather than failing to match. The
                    // guard, not route registration, is the access boundary (R4.4).
                    NavModule.entries.forEach { dest ->
                        composable(dest.route) {
                            GuardedDestination(
                                role = role,
                                module = dest.module,
                                onRedirect = { destination ->
                                    navigate(NavModule.forModule(destination).route)
                                },
                                onAuthorizationError = surfaceAuthorizationError,
                            ) {
                                // Real screens replace the placeholder per module as
                                // each module's task lands. The guard above is the
                                // access boundary regardless of the body rendered.
                                when (dest.module) {
                                    Module.Dashboard -> DashboardScreen(
                                        inboxNewCount = inboxUnreadCount,
                                    )

                                    Module.Accounts -> AccountsRoute(
                                        onLoginTelegram = onLoginTelegram,
                                    )

                                    else -> PlaceholderScreen(title = dest.label)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * Bottom navigation bar rendering [NavLayout.bottom] plus an optional "More" entry
 * (R5.2, R5.3). The active destination is highlighted via [NavigationBarItem]'s
 * `selected` flag; "More" is treated as selected while a drawer destination is open.
 */
@Composable
private fun NavBottomBar(
    layout: NavLayout,
    currentRoute: String?,
    inboxUnreadCount: Int,
    onSelect: (NavModule) -> Unit,
    onMore: () -> Unit,
) {
    NavigationBar {
        layout.bottom.forEach { dest ->
            NavigationBarItem(
                selected = currentRoute == dest.route,
                onClick = { onSelect(dest) },
                icon = { DestinationIcon(dest, inboxUnreadCount) },
                label = { Text(dest.label) },
                modifier = Modifier.semantics { contentDescription = dest.label },
            )
        }
        if (layout.showMore) {
            val moreSelected = layout.drawer.any { it.route == currentRoute }
            NavigationBarItem(
                selected = moreSelected,
                onClick = onMore,
                icon = {
                    Icon(imageVector = Icons.Filled.MoreHoriz, contentDescription = null)
                },
                label = { Text("More") },
                modifier = Modifier.semantics { contentDescription = "More" },
            )
        }
    }
}

/** Drawer list of the overflow [destinations], highlighting the active route. */
@Composable
private fun NavDrawerContent(
    destinations: List<NavModule>,
    currentRoute: String?,
    inboxUnreadCount: Int,
    onSelect: (NavModule) -> Unit,
) {
    Text(
        text = "TeleAutomation",
        style = androidx.compose.material3.MaterialTheme.typography.titleLarge,
        modifier = Modifier.padding(16.dp),
    )
    destinations.forEach { dest ->
        NavigationDrawerItem(
            selected = currentRoute == dest.route,
            onClick = { onSelect(dest) },
            icon = { DestinationIcon(dest, inboxUnreadCount) },
            label = { Text(dest.label) },
            modifier = Modifier
                .padding(NavigationDrawerItemDefaults.ItemPadding)
                .semantics { contentDescription = dest.label },
        )
    }
}

/**
 * Renders a destination's icon, overlaying the unread badge on the Inbox
 * destination using [UnreadBadgeFormatter.forNavInbox] (R5.6–R5.8).
 */
@Composable
private fun DestinationIcon(dest: NavModule, inboxUnreadCount: Int) {
    if (dest.module == Module.Inbox) {
        when (val badge = UnreadBadgeFormatter.forNavInbox(inboxUnreadCount)) {
            BadgeDisplay.None -> Icon(imageVector = dest.icon, contentDescription = null)
            is BadgeDisplay.Text -> BadgedBox(
                badge = {
                    Badge(
                        modifier = Modifier.semantics {
                            contentDescription = "${badge.value} unread"
                        },
                    ) { Text(badge.value) }
                },
            ) {
                Icon(imageVector = dest.icon, contentDescription = null)
            }
        }
    } else {
        Icon(imageVector = dest.icon, contentDescription = null)
    }
}

/**
 * Guards a single destination body for [role] (R4.4).
 *
 * On composition the destination's [module] is checked via [RoleModuleAccess.guard]:
 *  - [AccessDecision.Allowed] → the real [content] is composed and shown.
 *  - [AccessDecision.RedirectWithError] → [content] is **never** composed (the
 *    restricted screen is not shown); instead a one-shot [LaunchedEffect] surfaces
 *    the authorization error via [onAuthorizationError] and redirects to the role's
 *    default landing via [onRedirect]. The effect runs on first composition, so the
 *    redirect happens well within the 1s requirement and the user never sees the
 *    restricted content — this is what closes the deep-link hole.
 */
@Composable
private fun GuardedDestination(
    role: Role,
    module: Module,
    onRedirect: (Module) -> Unit,
    onAuthorizationError: (AuthorizationSignal) -> Unit,
    content: @Composable () -> Unit,
) {
    when (val decision = RoleModuleAccess.guard(role, module)) {
        AccessDecision.Allowed -> content()
        is AccessDecision.RedirectWithError -> {
            LaunchedEffect(role, module) {
                onAuthorizationError(AuthorizationSignal(decision.authorizationError))
                onRedirect(decision.destination)
            }
        }
    }
}

/**
 * Top-bar account menu surfacing the authenticated Operator's [username] in the
 * navigation area (R2.7) and offering the sign-out action wired to [onLogout]
 * (R2.4). When [username] is `null` (e.g. auth disabled) the header reads
 * "Account" so the sign-out action is still reachable.
 */
@Composable
private fun AccountMenu(username: String?, onLogout: () -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val accountLabel = username?.takeIf { it.isNotBlank() } ?: "Account"
    Box {
        IconButton(
            onClick = { expanded = true },
            modifier = Modifier.semantics {
                contentDescription = "Account: $accountLabel"
            },
        ) {
            Icon(
                imageVector = Icons.Filled.AccountCircle,
                contentDescription = null,
            )
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            Text(
                text = accountLabel,
                style = androidx.compose.material3.MaterialTheme.typography.titleSmall,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
            HorizontalDivider()
            DropdownMenuItem(
                text = { Text("Sign out") },
                onClick = {
                    expanded = false
                    onLogout()
                },
                leadingIcon = {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.Logout,
                        contentDescription = null,
                    )
                },
                modifier = Modifier.semantics { contentDescription = "Sign out" },
            )
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun NavScaffoldAdminPreview() {
    TeleAutomationTheme {
        NavScaffold(
            role = Role.ADMIN,
            inboxUnreadCount = 7,
            connectionState = ConnectionState.Connected,
            username = "admin",
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun NavScaffoldHandlerPreview() {
    TeleAutomationTheme {
        NavScaffold(
            role = Role.HANDLER,
            inboxUnreadCount = 0,
            connectionState = ConnectionState.Disconnected,
            username = "handler1",
        )
    }
}
