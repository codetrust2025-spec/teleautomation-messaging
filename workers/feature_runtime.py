"""Proxy views over prefixed AccountState fields (campaign_* / forwarding_*)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workers.account_state import AccountState


class FeatureRuntimeProxy:
    """Maps short names (cycle, success) to prefixed storage on AccountState."""

    def __init__(
        self,
        account: AccountState,
        prefix: str,
        aliases: dict[str, str] | None = None,
    ) -> None:
        object.__setattr__(self, "_account", account)
        object.__setattr__(self, "_prefix", prefix)
        object.__setattr__(self, "_aliases", aliases or {})

    def _key(self, name: str) -> str:
        return self._aliases.get(name, f"{self._prefix}{name}")

    def __getattr__(self, name: str):
        return getattr(self._account, self._key(name))

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(self._account, self._key(name), value)


_FORWARDING_ALIASES = {
    "forward_batch": "forwarding_batch",
    "forward_batch_total": "forwarding_batch_total",
    "forward_batch_size": "forwarding_batch_size",
    "forward_joined_total": "forwarding_joined_total",
    "failed_list": "forwarding_failed_list",
    "failure_counts": "forwarding_failure_counts",
}


def campaign_runtime(account: AccountState) -> FeatureRuntimeProxy:
    return FeatureRuntimeProxy(account, "campaign_", {})


def forwarding_runtime(account: AccountState) -> FeatureRuntimeProxy:
    return FeatureRuntimeProxy(account, "forwarding_", _FORWARDING_ALIASES)
