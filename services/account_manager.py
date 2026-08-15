"""
AccountManager — isolated per-account worker lifecycle.

Replaces AccountRegistry with explicit lifecycle states:
  RUNNING | SLEEPING | ERROR | STOPPED
"""

from __future__ import annotations

import asyncio
import os
from enum import Enum
from typing import Any, Awaitable, Callable

from core.account_info_store import load_account_info
from core.account_logging import account_log
from core.config import ACCOUNTS, ACCOUNT_SLOTS, MESSAGE_REWRITE_ENABLED
from core.groups_store import load_master_groups
from core.message_store import load_message, load_message_for_account
from core.session_manager import session_manager
from core.worker_persistence import (
    clear_all as clear_persisted_workers,
    load_running_slots,
    mark_running,
    mark_stopped,
)
from core.observability.account_metrics import metrics_store
from core.observability.alerts import alert_store
from events.event_bus import event_bus
from events.event_types import EventType
from messaging.queue_config import AUTO_RESTART_ON_CRASH
from services.account_runtime import AccountRuntime
from workers.account_worker import AccountWorker

OnChange = Callable[[], Awaitable[None]]


class LifecycleState(str, Enum):
    RUNNING = "RUNNING"
    SLEEPING = "SLEEPING"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class AccountManager:
    def __init__(self) -> None:
        self._runtimes: dict[str, AccountRuntime] = {}
        self._on_change: OnChange | None = None
        self.active_account: str | None = None
        self._lifecycle: dict[str, LifecycleState] = {
            s: LifecycleState.STOPPED for s in ACCOUNTS
        }
        self._crash_counts: dict[str, int] = {s: 0 for s in ACCOUNTS}
        self._health_monitor = None

    def set_on_change(self, cb: OnChange) -> None:
        self._on_change = cb
        for runtime in self._runtimes.values():
            runtime.set_on_change(self._handle_change)

    def set_health_monitor(self, monitor) -> None:
        self._health_monitor = monitor

    async def _handle_change(self) -> None:
        if self._on_change:
            await self._on_change()

    def _set_lifecycle(self, slot: str, state: LifecycleState) -> None:
        self._lifecycle[slot] = state

    def _derive_lifecycle(self, slot: str) -> LifecycleState:
        runtime = self._runtimes.get(slot)
        w = runtime.worker if runtime else None
        if w is None:
            return LifecycleState.STOPPED
        st = w.state
        if not st.running:
            return LifecycleState.STOPPED
        status = getattr(st, "status", None)
        if status is None:
            if st.campaign_running:
                status = st.campaign_status
            elif st.forwarding_running:
                status = st.forwarding_status
            else:
                status = "stopped"
        next_cycle_in = max(
            int(st.campaign_next_cycle_in or 0),
            int(st.forwarding_next_cycle_in or 0),
        )
        if status in ("flood_wait", "waiting") or st.heavy_rate_limit or next_cycle_in > 0:
            return LifecycleState.SLEEPING
        if status in ("recovering",) or (
            st.notification and "error" in st.notification.lower()
        ):
            return LifecycleState.ERROR
        return LifecycleState.RUNNING

    def register_new_slot(self, slot: str) -> None:
        """Register lifecycle maps after ACCOUNTS was extended at runtime."""
        from core.config import ACCOUNTS

        if slot not in ACCOUNTS:
            raise ValueError(f"Invalid slot: {slot}")
        if slot not in self._lifecycle:
            self._lifecycle[slot] = LifecycleState.STOPPED
        if slot not in self._crash_counts:
            self._crash_counts[slot] = 0

    def get_runtime(self, slot: str) -> AccountRuntime:
        if slot not in ACCOUNTS:
            raise ValueError(f"Invalid slot: {slot}")
        if slot not in self._runtimes:
            self._runtimes[slot] = AccountRuntime(slot, on_change=self._handle_change)
        return self._runtimes[slot]

    def get_worker(self, slot: str) -> AccountWorker:
        return self.get_runtime(slot).worker

    def all_workers(self) -> dict[str, AccountWorker]:
        return {s: self.get_worker(s) for s in ACCOUNTS}

    def all_runtimes(self) -> dict[str, AccountRuntime]:
        return {s: self.get_runtime(s) for s in ACCOUNTS}

    def get_status(self, account_id: str) -> dict[str, Any]:
        if account_id not in ACCOUNTS:
            raise ValueError(f"Invalid account_id: {account_id}")
        lifecycle = self._derive_lifecycle(account_id)
        self._set_lifecycle(account_id, lifecycle)
        runtime = self.get_runtime(account_id)
        w = runtime.worker
        q = runtime.queue
        return {
            "account_id": account_id,
            "lifecycle": lifecycle.value,
            "worker": w.state.to_dict(),
            "queue": q.status_dict(),
            "session_exists": session_manager.exists(account_id),
            "metrics": metrics_store.snapshot(account_id),
            "alerts": alert_store.for_account(account_id)[-10:],
            "crash_count": self._crash_counts.get(account_id, 0),
        }

    async def start_account(
        self,
        account_id: str,
        one_shot: bool = False,
        *,
        skip_refresh: bool = False,
        campaign: bool | None = None,
        forwarding: bool | None = None,
    ) -> bool:
        from core.account_shutdown import is_shutdown_active

        if is_shutdown_active(account_id):
            return False
        runtime = self.get_runtime(account_id)
        if await runtime.start(
            one_shot=one_shot,
            skip_refresh=skip_refresh,
            campaign=campaign,
            forwarding=forwarding,
        ):
            mark_running(account_id)
            self._set_lifecycle(account_id, LifecycleState.RUNNING)
            await event_bus.publish(
                EventType.ACCOUNT_STATE,
                account_id,
                {"lifecycle": LifecycleState.RUNNING.value},
            )
            return True
        return False

    async def stop_account(
        self,
        account_id: str,
        *,
        campaign: bool | None = None,
        forwarding: bool | None = None,
    ) -> None:
        await self.get_runtime(account_id).stop(
            release_session=False,
            campaign=campaign,
            forwarding=forwarding,
        )
        mark_stopped(account_id)
        self._set_lifecycle(account_id, LifecycleState.STOPPED)
        account_log(account_id, "Worker stopped", level="info")
        await event_bus.publish(
            EventType.ACCOUNT_STATE,
            account_id,
            {"lifecycle": LifecycleState.STOPPED.value},
        )

    async def stop_account_async(
        self,
        account_id: str,
        *,
        release_session: bool = True,
        wait: float = 1.0,
    ) -> None:
        await self.get_runtime(account_id).stop(wait=wait, release_session=release_session)
        mark_stopped(account_id)
        self._set_lifecycle(account_id, LifecycleState.STOPPED)

    async def restart_account(self, account_id: str, *, one_shot: bool = False) -> bool:
        account_log(account_id, "Restarting worker", level="info")
        ok = await self.get_runtime(account_id).restart(one_shot=one_shot)
        if ok:
            self._set_lifecycle(account_id, LifecycleState.RUNNING)
        return ok

    async def refresh_all_info(self) -> dict:
        info = {}
        from core import telegram_client

        for slot in ACCOUNTS:
            if telegram_client.any_login_exclusive():
                w = self.get_worker(slot)
                cached = w.state.account_info or load_account_info(slot)
                if cached:
                    info[slot] = cached
                continue
            w = self.get_worker(slot)
            if not w.state.account_info:
                cached = load_account_info(slot)
                if cached:
                    w.state.account_info = cached
                    info[slot] = cached
            live = await w.refresh_info(preserve_on_error=True)
            if live:
                info[slot] = live
            elif w.state.account_info:
                info[slot] = w.state.account_info
            await asyncio.sleep(0.5)
        if self.active_account is None or self.active_account not in ACCOUNTS:
            for slot in ACCOUNTS:
                if info.get(slot):
                    self.active_account = slot
                    break
        return info

    async def refresh_joined_counts(self, slot: str) -> dict | None:
        if slot not in ACCOUNTS:
            return None
        return await self.get_worker(slot).refresh_joined_stats()

    async def complete_login(self, slot: str, info: dict) -> bool:
        from core.account_info_store import save_account_info
        from services.dm_inbox_service import schedule_inbox_listener_refresh

        if slot not in ACCOUNTS or not info or not info.get("phone"):
            return False

        save_account_info(slot, info)
        w = self.get_worker(slot)
        w.state.account_info = info
        self.active_account = slot

        from core import telegram_client

        await telegram_client.finalize_login_exclusive(slot)
        try:
            schedule_inbox_listener_refresh(slot)
        except Exception:
            pass

        if w.state.running:
            await self.stop_account_async(slot, wait=1.0, release_session=True)

        await w.ensure_queue_processor()
        started = await self.start_account(slot, skip_refresh=True)
        return started

    async def logout_account(self, slot: str) -> None:
        from core.account_info_store import clear_account_info
        from core.login_pending import clear_pending
        from services.dm_inbox_service import suspend_for_login

        if slot not in ACCOUNTS:
            return

        mark_stopped(slot)
        from core import telegram_client

        telegram_client.set_login_exclusive(slot, False)

        w = self.get_worker(slot)
        w.stop()
        await w.stop_queue_processor()
        await self.get_runtime(slot).drain_queue()

        await self.stop_account_async(slot, wait=3.0, release_session=True)

        try:
            await suspend_for_login(slot)
        except Exception:
            pass

        client = telegram_client.get_client_ref(slot)
        if client is not None:
            try:
                if client.is_connected():
                    await client.log_out()
            except Exception:
                pass

        await session_manager.delete_session(slot)
        w.reset_after_logout()
        clear_account_info(slot)
        clear_pending(slot)
        self._set_lifecycle(slot, LifecycleState.STOPPED)

        if self.active_account == slot:
            self.active_account = None
            for s in ACCOUNT_SLOTS:
                if self.get_worker(s).state.account_info:
                    self.active_account = s
                    break

        account_log(slot, "Logout complete", level="info")

    async def clear_logs(self, slot: str) -> None:
        if slot in ACCOUNTS:
            await self.get_worker(slot).clear_logs()

    async def start_all_logged_in(self, one_shot: bool = False) -> list[str]:
        started: list[str] = []

        async def _start(slot: str) -> bool:
            w = self.get_worker(slot)
            if not w.state.account_info:
                w.state.account_info = load_account_info(slot)
            if w.state.account_info and not w.state.running:
                return await self.start_account(slot, one_shot=one_shot, skip_refresh=True)
            return False

        for slot in ACCOUNTS:
            if await _start(slot):
                started.append(slot)
                await asyncio.sleep(1.0)
        return started

    def stop_all(self) -> None:
        for slot in ACCOUNTS:
            self.get_worker(slot).stop()
        clear_persisted_workers()

    async def pause_all_workers(self, *, wait: float = 14.0) -> None:
        from core import telegram_client

        for slot in ACCOUNTS:
            self.get_worker(slot).stop()
        tasks = [
            runtime.worker.state.task
            for runtime in self._runtimes.values()
            if runtime.worker.state.task is not None and not runtime.worker.state.task.done()
        ]
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[asyncio.shield(t) for t in tasks], return_exceptions=True),
                    timeout=wait,
                )
            except (asyncio.TimeoutError, Exception):
                pass
        await telegram_client.abandon_all_sessions()

    async def resume_persisted_workers(self) -> list[str]:
        from core.config import BASE_DIR

        slots = load_running_slots()
        if not slots:
            return []
        await self.refresh_all_info()
        async def _resume(slot: str) -> str | None:
            w = self.get_worker(slot)
            session_path = os.path.join(BASE_DIR, ACCOUNTS[slot]) + ".session"
            if not w.state.account_info or not session_manager.exists(slot):
                mark_stopped(slot)
                w.reset_after_logout()
                return None
            from core.posting_mode import load_posting_mode

            pm = load_posting_mode(slot)
            campaign = pm.campaign_enabled
            forwarding = pm.forwarding_enabled
            if not w.state.running and await self.start_account(
                slot,
                skip_refresh=True,
                campaign=campaign,
                forwarding=forwarding,
            ):
                return slot
            if not w.state.account_info:
                mark_stopped(slot)
            return None

        results = await asyncio.gather(*[_resume(slot) for slot in slots])
        return [slot for slot in results if slot]

    def is_any_running(self) -> bool:
        return any(runtime.worker.state.running for runtime in self._runtimes.values())

    def build_ui_state(self) -> dict:
        account_states = {}
        account_status = {}
        from core.join_cycle import join_stats_for_ui
        from core.group_assignment import groups_for_slot
        from core.groups_store import load_master_groups

        master_groups = load_master_groups()

        from core.posting_mode import load_posting_mode

        for s, w in self.all_workers().items():
            w._sync_posting_mode_ui()
            pm = load_posting_mode(s)
            account_states[s] = {
                **w.state.to_dict(),
                "join_stats": join_stats_for_ui(s),
                "assigned_groups_count": len(groups_for_slot(s, master_groups)),
                "posting_mode_config": pm.to_dict(s),
            }
            lifecycle = self._derive_lifecycle(s)
            self._set_lifecycle(s, lifecycle)
            q = self.get_runtime(s).queue
            account_status[s] = {
                "lifecycle": lifecycle.value,
                "queue_depth": q.depth,
                "queue_max_size": q.max_size,
                "queue_processing": q.is_processing,
                "queue_high_watermark": q.high_watermark,
                "metrics": metrics_store.snapshot(s),
                "alerts": alert_store.for_account(s)[-5:],
                "crash_count": self._crash_counts.get(s, 0),
            }

        active = self.active_account
        active_state = account_states.get(active, {}) if active else {}
        account_messages = {s: load_message_for_account(s) for s in ACCOUNT_SLOTS}

        from core.daily_stats import compute_daily_stats
        from core.subscription_accounts import compute_subscription_slots, enrich_account_info

        account_info = {s: w.state.account_info for s, w in self.all_workers().items()}
        # Auto 24h rollover runs in server._auto_stats_reset_loop — avoid blocking WS here.
        daily_stats = compute_daily_stats(list(ACCOUNT_SLOTS))
        enriched_info = {
            s: enrich_account_info(s, account_info.get(s)) if account_info.get(s) else None
            for s in ACCOUNT_SLOTS
        }
        from core.joined_membership import membership_meta

        for s in ACCOUNT_SLOTS:
            info = enriched_info.get(s)
            if info:
                enriched_info[s] = {**info, **membership_meta(info)}

        ui = {
            "account_slots": list(ACCOUNT_SLOTS),
            "account_info": enriched_info,
            "subscription_slots": compute_subscription_slots(enriched_info),
            "running": active_state.get("running", False),
            "notification": active_state.get("notification", ""),
            "total": len(load_master_groups()),
            "success": active_state.get("success", 0),
            "failed": active_state.get("failed", 0),
            "current_group": active_state.get("current_group", ""),
            "success_list": active_state.get("success_list", []),
            "failed_list": active_state.get("failed_list", []),
            "logs": active_state.get("logs", []),
            "message_id": None,
            "cycle": active_state.get("cycle", 0),
            "active_groups": active_state.get("active_groups", 0),
            "active_account": active,
            "custom_message": (
                load_message_for_account(active) if active else load_message()
            ),
            "account_messages": account_messages,
            "account_states": account_states,
            "account_status": account_status,
            "message_rewrite_enabled": MESSAGE_REWRITE_ENABLED,
            "cycle_message_preview": active_state.get("cycle_message_preview", ""),
            "daily_stats": daily_stats,
            "fleet_metrics": metrics_store.all_snapshots(),
            "fleet_alerts": alert_store.recent(limit=30),
            "posting_modes": {
                s: load_posting_mode(s).to_dict(s) for s in ACCOUNT_SLOTS
            },
        }
        try:
            from services.forward_message_service import forward_message_service

            ui["forward_message_jobs"] = forward_message_service.all_jobs_dict(
                list(ACCOUNT_SLOTS)
            )
        except Exception:
            ui["forward_message_jobs"] = {}
        try:
            from core.fleet_rate_coordinator import fleet_rate_coordinator

            ui["fleet_rate"] = fleet_rate_coordinator.snapshot()
        except Exception:
            pass
        from core.account_shutdown import list_shutdowns, shutdown_info_for_ui

        ui["account_shutdown"] = {
            s: shutdown_info_for_ui(s) for s in ACCOUNT_SLOTS
        }
        ui["shutdown_list"] = list_shutdowns()
        return ui

    def reset_stats_display_counters(self, account_id: str | None = None) -> None:
        """
        Clear live tick/cycle counters shown in the UI after a stats reset.
        Does not stop workers or delete Telegram chats; send_history cutoff is separate.
        """
        from core.posting_mode import load_posting_mode, save_posting_mode

        slots = [account_id] if account_id else list(ACCOUNTS)
        for slot in slots:
            w = self.get_worker(slot)
            st = w.state
            st.campaign_success = 0
            st.campaign_failed = 0
            st.campaign_skipped_already_posted = 0
            st.campaign_skipped_cooldown = 0
            st.campaign_skipped_other = 0
            st.campaign_active_groups = 0
            st.campaign_current_group = ""
            st.campaign_success_list = []
            st.campaign_failed_list = []
            st.forwarding_success = 0
            st.forwarding_failed = 0
            st.forwarding_skipped_already_posted = 0
            st.forwarding_active_groups = 0
            st.forwarding_current_group = ""
            st.forwarding_batch = 0
            st.forwarding_batch_total = 0
            pm = load_posting_mode(slot)
            pm.forwarding.tick_pending_keys = []
            pm.forwarding.tick_group_offset = 0
            save_posting_mode(slot, pm)


manager = AccountManager()
