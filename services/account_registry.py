"""
Backward compatibility — prefer services.account_manager.manager.

AccountRegistry is an alias for AccountManager.
"""

from services.account_manager import AccountManager, LifecycleState, manager

registry = manager
AccountRegistry = AccountManager

__all__ = ["AccountRegistry", "AccountManager", "LifecycleState", "manager", "registry"]
