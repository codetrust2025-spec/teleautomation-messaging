"""Account-local timing and policy strategy.

The default strategy intentionally ignores fleet-wide pressure so one
account's flood/retry behavior cannot slow another account in Option A.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountTimingSnapshot:
    account_id: str
    fleet_pressure: float = 0.0
    delay_multiplier: float = 1.0
    recently_flooded: bool = False


class AccountTimingPolicy:
    """Per-account policy surface, replaceable by a process boundary later."""

    def __init__(self, account_id: str, *, fleet_coordination: bool = False) -> None:
        self.account_id = account_id
        self.fleet_coordination = fleet_coordination

    def snapshot(self) -> AccountTimingSnapshot:
        if not self.fleet_coordination:
            return AccountTimingSnapshot(account_id=self.account_id)

        from core.fleet_rate_coordinator import fleet_rate_coordinator

        return AccountTimingSnapshot(
            account_id=self.account_id,
            fleet_pressure=fleet_rate_coordinator.fleet_pressure(),
            delay_multiplier=fleet_rate_coordinator.delay_multiplier(),
            recently_flooded=fleet_rate_coordinator.account_recently_flooded(self.account_id),
        )

    def cycle_stagger_seconds(self) -> int:
        if not self.fleet_coordination:
            return 0

        from core.fleet_rate_coordinator import fleet_rate_coordinator
        from core.group_assignment import slot_index

        return int(fleet_rate_coordinator.should_stagger_account(self.account_id, slot_index(self.account_id)))

    def record_flood(self, seconds: int) -> None:
        if not self.fleet_coordination:
            return

        from core.fleet_rate_coordinator import fleet_rate_coordinator

        fleet_rate_coordinator.record_flood(self.account_id, seconds=seconds)
