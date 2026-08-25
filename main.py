"""
FastAPI entrypoint — thin API layer.
Execution lives in workers/ and features/ only.
Accounts run independently; no rotation scheduler.
"""

import asyncio
import json
import os
import shutil
from datetime import datetime

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from core import broadcast
from core.config import ACCOUNTS, ACCOUNT_SLOTS, BASE_DIR, DATA_DIR, GROUPS_FILE, MESSAGE_FILE
from core.groups_store import (
    _normalize_group_name,
    build_group_lists,
    collect_all_dead_for_upload,
    ensure_groups_loaded,
    ensure_invalid_registry_backfill,
    is_valid_group_username,
    load_account_dead,
    load_master_groups,
    normalize_upload_username,
    save_master_groups,
)
from core.config import MESSAGE_REWRITE_ENABLED
from core.message_rewrite import preview_cycle_message
from core.message_store import (
    load_message,
    load_message_for_account,
    save_message,
    save_message_for_account,
)
from core import telegram_client
from telethon import TelegramClient
from core.account_info_store import (
    clear_account_info,
    duplicate_phone_login_message,
    find_logged_in_slot_by_phone,
    load_account_info,
    save_account_info,
)
from core.login_pending import clear_pending, load_pending, save_pending
from core.startup_workers import start_optional_workers
from core.worker_persistence import log_reload_event
from services.account_manager import manager
from events.event_bus import event_bus
from events.event_types import EventType
from core.admin_dashboard import install_admin_dashboard


def _load_project_dotenv() -> None:
    """Load .env into os.environ so PM2/uvicorn workers see AI_API_KEY etc."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except ImportError:
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = val.strip().strip('"').strip("'")


_load_project_dotenv()

registry = manager  # backward-compatible alias

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
install_admin_dashboard(app)

from core.dashboard_auth_api import install_dashboard_auth

install_dashboard_auth(app)

from core.voice_call_api import install_voice_call_routes

install_voice_call_routes(app)

from core.web_push_api import install_web_push_routes

install_web_push_routes(app)

from core.whatsapp_api import install_whatsapp_routes

install_whatsapp_routes(app)

from core.internal_api import install_internal_routes

install_internal_routes(app)

from core.demo_tools_api import install_demo_tools_routes

install_demo_tools_routes(app)


def _require_fleet_admin(request: Request) -> None:
    from core.dashboard_access import require_fleet_admin

    require_fleet_admin(request)


# Per-slot login state — no cross-account coupling
login_state: dict[str, dict] = {
    slot: {"phone": None, "phone_code_hash": None} for slot in ACCOUNTS
}


def _sync_login_state_slots() -> None:
    """Ensure login_state has an entry for every configured account slot."""
    from core.config import ACCOUNTS as live_accounts

    for slot in live_accounts:
        login_state.setdefault(slot, {"phone": None, "phone_code_hash": None})


def _slot_valid(slot: str) -> bool:
    from core.config import ACCOUNTS as live_accounts

    return slot in live_accounts


def _get_login_pending(slot: str) -> dict | None:
    """Memory first, then disk — survives uvicorn auto-reload between send & verify."""
    ls = login_state.get(slot) or {}
    if ls.get("phone") and ls.get("phone_code_hash"):
        return ls
    disk = load_pending(slot)
    if disk:
        login_state[slot] = disk
        return disk
    return None


async def _ensure_login_client(slot: str) -> TelegramClient:
    """Login/verify client — never opens a second SQLite session while one exists."""
    telegram_client.set_login_exclusive(slot, True)
    return await telegram_client.get_login_client(slot)


async def _prepare_login_slot(slot: str) -> None:
    """Stop worker and clear session files; OTP uses in-memory StringSession only."""
    await telegram_client.quiesce_slot_for_login(slot)


def _first_logged_in_slot(exclude: str | None = None) -> str | None:
    for slot in ACCOUNT_SLOTS:
        if exclude and slot == exclude:
            continue
        if registry.get_worker(slot).state.account_info:
            return slot
    return None


def _migrate_legacy_files() -> None:
    """One-time copy of root-level data files into data/."""
    os.makedirs(DATA_DIR, exist_ok=True)
    legacy_groups = os.path.join(BASE_DIR, "groups_list.json")
    legacy_msg = os.path.join(BASE_DIR, "custom_message.txt")
    if os.path.exists(legacy_groups) and not os.path.exists(GROUPS_FILE):
        shutil.copy2(legacy_groups, GROUPS_FILE)
    if os.path.exists(legacy_msg) and not os.path.exists(MESSAGE_FILE):
        shutil.copy2(legacy_msg, MESSAGE_FILE)
    ensure_groups_loaded()


async def _push_state() -> None:
    state = await asyncio.to_thread(registry.build_ui_state)
    await broadcast.broadcast({"type": "state", **state})


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    from core import dashboard_auth_vps as dash_auth

    profile = dash_auth.operator_profile_from_cookies(dict(websocket.cookies))
    if not dash_auth.is_admin_profile(profile):
        await websocket.close(code=4403, reason="Authentication required")
        return
    await websocket.accept()
    broadcast.active_connections.append(websocket)
    broadcast.connection_profiles[websocket] = profile
    full = await asyncio.to_thread(registry.build_ui_state)
    await websocket.send_json({"type": "state", **full})
    if _membership_scheduler is not None:
        _membership_scheduler.schedule_stale_refresh(reason="dashboard_open")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict) or msg.get("type") != "voice":
                continue
            action = str(msg.get("action") or "").strip().lower()
            session_id = str(msg.get("session_id") or "").strip()
            if not session_id:
                continue
            from core import voice_signaling
            from services import voice_call_service as voice_svc

            if action == "register":
                await voice_signaling.register_peer(session_id, "operator", websocket)
            elif action == "signal":
                signal = msg.get("signal") if isinstance(msg.get("signal"), dict) else {}
                await voice_svc.handle_operator_signal(session_id, signal)
    except WebSocketDisconnect:
        pass
    finally:
        broadcast.connection_profiles.pop(websocket, None)
        if websocket in broadcast.active_connections:
            broadcast.active_connections.remove(websocket)


CODE_VERSION = "2026-05-23-account-isolation"
_persist_running_task: asyncio.Task | None = None
_health_monitor = None
_membership_scheduler = None
_shutdown_monitor = None
_start_all_task: asyncio.Task | None = None


async def _bootstrap_missing_joined_counts() -> None:
    """First login / stale membership: queue joined-count scan when needed."""
    from core.account_info_store import load_account_info
    from core.join_cycle import load_join_state
    from datetime import datetime, timezone

    def _needs_membership_rescan(slot: str, info: dict) -> bool:
        if info.get("joined_total") is None:
            return True
        js = load_join_state(slot)
        last_join = js.get("last_new_join_at")
        if not last_join:
            return False
        updated = info.get("joined_updated_at")
        if not updated:
            return True
        try:
            lj = datetime.fromisoformat(str(last_join).replace("Z", "+00:00"))
            up = datetime.strptime(str(updated), "%Y-%m-%d %H:%M UTC").replace(
                tzinfo=timezone.utc
            )
            return lj > up
        except Exception:
            return False

    await asyncio.sleep(8.0)
    for slot in ACCOUNTS:
        if telegram_client.any_login_exclusive():
            return
        w = registry.get_worker(slot)
        info = w.state.account_info or load_account_info(slot)
        if not info or not info.get("phone"):
            continue
        if not _needs_membership_rescan(slot, info):
            continue
        if w.state.running:
            w.request_joined_scan()
            continue
        try:
            await registry.refresh_joined_counts(slot)
            await _push_state()
        except Exception:
            pass
        await asyncio.sleep(6.0)


async def _persist_running_workers_loop() -> None:
    """Heartbeat: save running workers so reload survives abrupt shutdown."""
    from core.worker_persistence import save_running_slots

    while True:
        try:
            await asyncio.sleep(30)
            running = [
                s
                for s, runtime in registry.all_runtimes().items()
                if runtime.worker.state.running
            ]
            if running:
                save_running_slots(running)
        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def _auto_stats_reset_loop() -> None:
    """Roll daily dashboard counters every 24h and push fresh state to clients."""
    from core.daily_stats import refresh_daily_stats
    from core.join_cycle import join_stats_for_ui
    from core.stats_reset import get_reset_at_iso

    await asyncio.sleep(30.0)
    while True:
        try:
            daily_stats, auto_reset = await asyncio.to_thread(
                refresh_daily_stats, list(ACCOUNTS)
            )
            if auto_reset:
                reset_slots = (
                    list(ACCOUNTS)
                    if auto_reset.scope == "global"
                    else list(auto_reset.account_ids)
                )
                if auto_reset.scope == "global":
                    registry.reset_stats_display_counters(None)
                else:
                    for slot in auto_reset.account_ids:
                        registry.reset_stats_display_counters(slot)
                account_states_patch = {
                    slot: registry.get_worker(slot).state.to_dict()
                    for slot in reset_slots
                }
                reset_scope = "global" if auto_reset.scope == "global" else auto_reset.account_ids[0]
                await event_bus.publish(
                    EventType.STATS_RESET,
                    reset_scope,
                    {
                        "reset_timestamp": auto_reset.reset_timestamp,
                        "reset_at": get_reset_at_iso(
                            None if auto_reset.scope == "global" else auto_reset.account_ids[0]
                        ),
                        "account_id": None if auto_reset.scope == "global" else auto_reset.account_ids[0],
                        "scope": auto_reset.scope,
                        "auto": True,
                        "daily_stats": daily_stats,
                        "account_states": account_states_patch,
                    },
                    push_state=True,
                    broadcast_ws=True,
                )
                await broadcast.broadcast({"type": "daily_stats", "daily_stats": daily_stats})
                await _push_state()
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(60.0)


async def _startup_background() -> None:
    """Telethon refresh + worker resume — must not block HTTP/WebSocket."""
    from core.worker_persistence import log_reload_event

    try:
        await _push_state()
        await registry.refresh_all_info()
        await _push_state()
        await asyncio.sleep(1.0)
        resumed = await registry.resume_persisted_workers()
        if resumed:
            log_reload_event(f"Auto-resumed workers after reload: {', '.join(resumed)}")
            await _push_state()
        asyncio.create_task(_bootstrap_missing_joined_counts())
        from services.dm_inbox_service import ensure_inbox_listeners

        async def _inbox_listeners_after_workers() -> None:
            await asyncio.sleep(3.0)
            await ensure_inbox_listeners()

        asyncio.create_task(_inbox_listeners_after_workers())

        async def _inbox_periodic_sync() -> None:
            from core.config import ACCOUNTS
            from services.dm_inbox_service import (
                ensure_inbox_listener,
                sync_stored_conversations,
            )

            await asyncio.sleep(12.0)
            while True:
                if telegram_client.any_login_exclusive():
                    await asyncio.sleep(5.0)
                    continue
                for slot in ACCOUNTS:
                    try:
                        await ensure_inbox_listener(slot)
                        await sync_stored_conversations(
                            slot, per_chat_limit=12, max_chats=6
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(2.0)
                await asyncio.sleep(30.0)

        asyncio.create_task(_inbox_periodic_sync())
        asyncio.create_task(_auto_stats_reset_loop())

        # Every optional worker starts on its own. They used to share this
        # function's single try/except, so the first one that could not start
        # took every worker below it down silently — which is what happened:
        # `core.daily_briefing` belongs to Operations and has never existed in
        # this repository, so its unguarded import raised ModuleNotFoundError
        # on every boot and neither worker below it ever ran.
        def _start_karthik_inbox_sweep() -> None:
            from core.karthik_inbox_sweep import start

            start()

        # The interview reminder loop is not started here. It lives in
        # Operations (`services/interview_reminder_loop.py`), which starts and
        # stops it in its own lifespan; this repository has never carried the
        # module. Registering it here only ever produced a startup failure,
        # hidden until the daily-briefing import above it stopped masking it.
        start_optional_workers(
            (("Karthik inbox sweep", _start_karthik_inbox_sweep),),
            log=log_reload_event,
        )
    except Exception as e:
        log_reload_event(f"Startup background task error: {type(e).__name__}: {e}")


def _repair_inbox_conversation_keys() -> None:
    """Idempotent: move phone_e164 inbox keys to numeric user_id keys."""
    from core.config import ACCOUNT_SLOTS
    from core.dm_store import repair_conversation_keys

    total = 0
    for slot in ACCOUNT_SLOTS:
        try:
            total += len(repair_conversation_keys(slot))
        except Exception:
            pass
    if total:
        from core.worker_persistence import log_reload_event

        log_reload_event(f"Inbox key repair: {total} conversation(s) fixed")


@app.on_event("startup")
async def startup():
    global _persist_running_task, _health_monitor, _membership_scheduler
    if os.getenv("TELEAUTOMATION_SAFE_UI_MODE", "false").lower() in {"1", "true", "yes"}:
        # Local UI preview: serve APIs/static assets without reconnecting Telegram,
        # resuming persisted workers, starting schedulers, or contacting providers.
        return
    from core.config import warn_default_telegram_creds
    from core.migrations.runner import apply_migrations

    apply_migrations()
    warn_default_telegram_creds()
    _repair_inbox_conversation_keys()
    _sync_login_state_slots()
    telegram_client.sync_slots()
    _migrate_legacy_files()
    manager.set_on_change(_push_state)
    event_bus.set_state_push(_push_state)
    from services.forward_message_service import forward_message_service

    forward_message_service.set_on_change(_push_state)
    forward_message_service.recover_jobs_after_restart()

    from events.subscribers import register_event_subscribers

    register_event_subscribers()

    from core.auto_reload import log_process_start

    log_process_start(version=CODE_VERSION)

    for slot in ACCOUNTS:
        cached = load_account_info(slot)
        if cached:
            registry.get_worker(slot).state.account_info = cached

    _persist_running_task = asyncio.create_task(_persist_running_workers_loop())
    asyncio.create_task(_startup_background())

    from core.health_monitor import HealthMonitor

    _health_monitor = HealthMonitor(manager)
    manager.set_health_monitor(_health_monitor)
    _health_monitor.start()

    from core.joined_membership_scheduler import JoinedMembershipScheduler

    _membership_scheduler = JoinedMembershipScheduler(manager, _push_state)
    _membership_scheduler.start()

    from services.opportunity_event_producer import start_outbox_dispatcher

    start_outbox_dispatcher()

    try:
        from core.karthik_inbox_sweep import start as start_karthik_inbox_sweep

        start_karthik_inbox_sweep()
    except Exception as e:
        log_reload_event(f"Karthik inbox sweep start failed: {type(e).__name__}: {e}")

    global _shutdown_monitor
    from core.account_shutdown_monitor import AccountShutdownMonitor

    _shutdown_monitor = AccountShutdownMonitor(manager)
    _shutdown_monitor.start()



@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown — persist workers, disconnect Telethon, resume after reload."""
    global _persist_running_task, _health_monitor, _membership_scheduler, _shutdown_monitor

    from services.opportunity_event_producer import stop_outbox_dispatcher

    await stop_outbox_dispatcher()


    if _shutdown_monitor is not None:
        await _shutdown_monitor.stop()
        _shutdown_monitor = None

    if _membership_scheduler is not None:
        await _membership_scheduler.stop()
        _membership_scheduler = None

    if _health_monitor is not None:
        await _health_monitor.stop()
        _health_monitor = None

    if _persist_running_task is not None:
        _persist_running_task.cancel()
        try:
            await _persist_running_task
        except asyncio.CancelledError:
            pass
        _persist_running_task = None

    from core.auto_reload import log_process_shutdown, reload_enabled
    from core.system_lifecycle import graceful_shutdown

    running = await graceful_shutdown(registry)
    if reload_enabled():
        log_process_shutdown(running_workers=running)


# ── Forwarding control (per-account independent) ──────────────────────────────

async def _start_all_background(one_shot: bool = False) -> None:
    global _start_all_task
    try:
        started = await registry.start_all_logged_in(one_shot=one_shot)
        if started:
            await _push_state()
    finally:
        _start_all_task = None


@app.post("/start", dependencies=[Depends(_require_fleet_admin)])
async def start_all():
    """Queue start for every logged-in account; return immediately for UI responsiveness."""
    global _start_all_task
    if _start_all_task is not None and not _start_all_task.done():
        return {"status": "queued", "accounts": [], "message": "Start all already in progress"}
    if not any(registry.get_runtime(slot).has_login() for slot in ACCOUNTS):
        return {"status": "error", "accounts": [], "message": "No logged-in accounts"}
    _start_all_task = asyncio.create_task(_start_all_background(one_shot=False))
    return {"status": "queued", "accounts": [], "message": "Starting logged-in accounts in background"}


@app.post("/start-test", dependencies=[Depends(_require_fleet_admin)])
async def start_test_all():
    global _start_all_task
    if _start_all_task is not None and not _start_all_task.done():
        return {"status": "queued", "accounts": [], "message": "Start all already in progress"}
    if not any(registry.get_runtime(slot).has_login() for slot in ACCOUNTS):
        return {"status": "error", "accounts": [], "message": "No logged-in accounts"}
    _start_all_task = asyncio.create_task(_start_all_background(one_shot=True))
    return {"status": "queued", "accounts": [], "message": "Starting one test cycle in background"}


@app.post("/stop", dependencies=[Depends(_require_fleet_admin)])
async def stop_all():
    registry.stop_all()
    await _push_state()
    return {"status": "stopped", **registry.build_ui_state()}


@app.post("/account/{slot}/start", dependencies=[Depends(_require_fleet_admin)])
async def start_account(
    slot: str,
    one_shot: bool = Query(False),
    feature: str = Query(""),
):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    campaign = forwarding = None
    feat = (feature or "").strip().lower()
    if feat == "campaign":
        campaign = True
    elif feat == "forwarding":
        forwarding = True
    elif feat and feat not in ("all", "both"):
        return {"status": "error", "message": "feature must be campaign, forwarding, or empty"}
    from core.account_shutdown import is_shutdown_active, shutdown_info_for_ui

    if is_shutdown_active(slot):
        info = shutdown_info_for_ui(slot) or {}
        return {
            "status": "error",
            "message": "Account is on shutdown list (no posts for 6+ hours). Clear shutdown to start.",
            "shutdown": info,
        }
    if not await registry.start_account(
        slot,
        one_shot=one_shot,
        campaign=campaign,
        forwarding=forwarding,
    ):
        w = registry.get_worker(slot)
        if not w.state.account_info:
            return {"status": "error", "message": f"{slot} not logged in"}
        if not (w.state.campaign_running or w.state.forwarding_running):
            from core.posting_mode import load_posting_mode

            cfg = load_posting_mode(slot)
            if not cfg.campaign_enabled and not cfg.forwarding_enabled:
                return {"status": "error", "message": "Enable campaign or forwarding first"}
        return {"status": "already_running"}
    await _push_state()
    return {"status": "started", "slot": slot, "feature": feat or "all"}


@app.post("/account/{slot}/shutdown", dependencies=[Depends(_require_fleet_admin)])
async def put_account_shutdown(slot: str):
    """Manually move an account to the shutdown (rest) list and stop it."""
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.account_shutdown import put_on_shutdown_list
    from core.worker_persistence import mark_stopped

    w = registry.get_worker(slot)
    if not w.state.account_info:
        return {"status": "error", "message": f"{slot} not logged in"}
    was_running = bool(w.state.running)
    put_on_shutdown_list(slot, reason="manual", was_running=was_running)
    try:
        await registry.stop_account(slot)
    except Exception:
        pass
    mark_stopped(slot)
    await _push_state()
    return {"status": "ok", "slot": slot, **registry.build_ui_state()}


@app.post("/account/{slot}/shutdown/clear", dependencies=[Depends(_require_fleet_admin)])
async def clear_account_shutdown(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.account_shutdown import clear_shutdown

    if not clear_shutdown(slot):
        return {"status": "not_found", "slot": slot}
    await _push_state()
    return {"status": "ok", "slot": slot, **registry.build_ui_state()}


@app.post("/account/shutdown/clear-all", dependencies=[Depends(_require_fleet_admin)])
@app.post("/shutdown/clear-all", dependencies=[Depends(_require_fleet_admin)])
async def clear_all_shutdowns_route(body: dict | None = None):
    """Return all accounts to Campaign/Forwarding tabs; optional stats reset for shutdown test cycle."""
    from core.account_shutdown import clear_all_shutdowns

    payload = body or {}
    cleared = clear_all_shutdowns()
    if payload.get("reset_stats") and cleared:
        from core.join_cycle import daily_join_count_for_reset
        from core.send_stats import invalidate_cache
        from core.stats_reset import StatsResetDebounced, set_reset_timestamp

        for slot in cleared:
            if slot not in ACCOUNTS:
                continue
            try:
                set_reset_timestamp(
                    account_id=slot,
                    join_baselines={slot: daily_join_count_for_reset(slot)},
                )
            except StatsResetDebounced:
                pass
            invalidate_cache(slot)
    await _push_state()
    return {
        "status": "ok",
        "cleared": cleared,
        "cleared_count": len(cleared),
        "reset_stats": bool(payload.get("reset_stats")),
        **registry.build_ui_state(),
    }


@app.post("/account/{slot}/stop", dependencies=[Depends(_require_fleet_admin)])
async def stop_account(slot: str, feature: str = Query("")):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    feat = (feature or "").strip().lower()
    campaign = forwarding = None
    if feat == "campaign":
        campaign = False
    elif feat == "forwarding":
        forwarding = False
    elif feat and feat not in ("all", "both"):
        return {"status": "error", "message": "feature must be campaign, forwarding, or empty"}
    await registry.stop_account(slot, campaign=campaign, forwarding=forwarding)
    await _push_state()
    return {"status": "stopped", "slot": slot, "feature": feat or "all", **registry.build_ui_state()}


@app.post("/account/{slot}/display-name")
async def set_account_display_name(slot: str, body: dict):
    """Set dashboard profile label for one account (does not change Telegram)."""
    if slot not in ACCOUNTS:
        return {"success": False, "error": "Invalid slot"}
    payload = body or {}
    display_name = str(payload.get("display_name") or "").strip()
    if not display_name:
        return {"success": False, "error": "Display name cannot be empty"}
    if len(display_name) > 48:
        return {"success": False, "error": "Display name too long (max 48 characters)"}

    info = load_account_info(slot)
    if not info or not info.get("phone"):
        return {"success": False, "error": "Account not logged in"}

    save_account_info(slot, {**info, "display_name": display_name})
    w = registry.get_worker(slot)
    refreshed = load_account_info(slot)
    if refreshed:
        w.state.account_info = refreshed
    await _push_state()
    return {"success": True, "account_info": w.state.account_info}


@app.get("/account/{slot}/posting-mode")
async def get_posting_mode(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.posting_mode import load_posting_mode

    return {"status": "ok", **load_posting_mode(slot).to_dict(slot)}


@app.post("/account/{slot}/posting-mode")
async def set_posting_mode_endpoint(slot: str, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.posting_mode import set_posting_mode

    payload = body or {}
    mode = str(payload.get("mode") or "").strip()
    forward_source_type = payload.get("forward_source_type")
    if forward_source_type is None:
        forward_source_type = payload.get("source_type")
    forward_dispatch = payload.get("forward_dispatch")
    campaign_enabled = payload.get("campaign_enabled")
    forwarding_enabled = payload.get("forwarding_enabled")
    if (
        not mode
        and forward_source_type is None
        and forward_dispatch is None
        and campaign_enabled is None
        and forwarding_enabled is None
    ):
        return {
            "status": "error",
            "message": "mode, campaign_enabled, forwarding_enabled, forward_source_type, or forward_dispatch required",
        }
    try:
        cfg = set_posting_mode(
            slot,
            mode,
            forward_source_type=forward_source_type,
            forward_dispatch=forward_dispatch,
            campaign_enabled=campaign_enabled,
            forwarding_enabled=forwarding_enabled,
        )
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    w = registry.get_worker(slot)
    w._sync_posting_mode_ui()
    await _push_state()
    return {"status": "ok", **cfg.to_dict(slot)}


@app.post("/account/{slot}/forwarding/source")
async def set_forwarding_source_endpoint(slot: str, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.posting_mode import set_forwarding_source

    w = registry.get_worker(slot)
    if w.state.running:
        return {
            "status": "error",
            "message": "Stop the worker before changing forward source",
        }
    payload = body or {}
    try:
        cfg = set_forwarding_source(
            slot,
            source_url=payload.get("source_url"),
            source_peer=payload.get("source_peer"),
            source_message_id=payload.get("source_message_id"),
        )
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    w._sync_posting_mode_ui()
    await _push_state()
    return {"status": "ok", **cfg.to_dict(slot)}


def _worker_running(slot: str) -> bool:
    return bool(registry.get_worker(slot).state.running)


@app.get("/forward-message/settings")
async def forward_message_settings_get():
    from services.forward_message_service import forward_message_service

    return {"status": "ok", "settings": forward_message_service.get_settings()}


@app.post("/forward-message/settings")
async def forward_message_settings_post(body: dict):
    from services.forward_message_service import forward_message_service

    try:
        settings = forward_message_service.save_settings(body or {})
        return {"status": "ok", "settings": settings}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@app.get("/account/{slot}/forward-message/groups")
async def forward_message_groups(slot: str, force_refresh: bool = False):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services.forward_message_service import forward_message_service

    try:
        payload = await forward_message_service.list_joined_groups(
            slot, force_refresh=bool(force_refresh)
        )
        return {"status": "ok", **payload}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/account/{slot}/forward-message/preview")
async def forward_message_preview(slot: str, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services.forward_message_service import forward_message_service

    payload = body or {}
    try:
        job = await forward_message_service.resolve_source(
            slot,
            source_url=str(payload.get("source_url") or "").strip(),
            source_peer=str(payload.get("source_peer") or "").strip(),
            source_message_id=int(payload.get("source_message_id") or 0),
            worker_running=_worker_running(slot),
        )
        return {"status": "ok", "job": job}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/account/{slot}/forward-message/job")
async def forward_message_job_status(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services.forward_message_service import forward_message_service

    return {"status": "ok", "job": forward_message_service.job_dict(slot)}


@app.post("/account/{slot}/forward-message/start", dependencies=[Depends(_require_fleet_admin)])
async def forward_message_start(slot: str, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services.forward_message_service import forward_message_service

    payload = body or {}
    target_ids = payload.get("target_ids") or payload.get("targets") or []
    try:
        batch_size = payload.get("batch_size")
        job = await forward_message_service.start_job(
            slot,
            source_url=str(payload.get("source_url") or "").strip(),
            source_peer=str(payload.get("source_peer") or "").strip(),
            source_message_id=int(payload.get("source_message_id") or 0),
            target_ids=target_ids,
            batch_size=int(batch_size) if batch_size is not None else None,
            worker_running=_worker_running(slot),
            use_posting_mode_source=bool(payload.get("use_posting_mode_source", True)),
            human_pace=bool(payload.get("human_pace", True)),
        )
        await _push_state()
        return {"status": "ok", "job": job}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/account/{slot}/forward-cycle/selection")
async def forward_cycle_selection_get(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.posting_mode import load_posting_mode

    cfg = load_posting_mode(slot)
    return {
        "status": "ok",
        "target_ids": list(cfg.forwarding.forward_selected_target_ids or []),
        "forward_dispatch": cfg.forwarding.forward_dispatch,
    }


@app.get("/account/{slot}/forward-intelligence")
async def forward_intelligence_stats(slot: str):
    """Get forwarding intelligence statistics and adaptive timing info"""
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}

    try:
        from core.forward_intelligence import load_forward_intelligence

        intel = load_forward_intelligence(slot)
        stats = intel.get_stats()

        # Add next tick prediction
        health_score = ACCOUNTS[slot].get("health_score", 100.0)
        next_interval = intel.compute_next_tick_interval(health_score)
        should_skip, skip_reason = intel.should_skip_tick(health_score)

        return {
            "status": "ok",
            "intelligence": {
                "stats": stats,
                "next_tick_interval_seconds": next_interval,
                "next_tick_interval_minutes": round(next_interval / 60, 1),
                "should_skip_next": should_skip,
                "skip_reason": skip_reason if should_skip else None,
                "dead_peers_sample": list(intel.get_dead_peer_set())[:20],  # First 20
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/account/{slot}/forward-cycle/selection")
async def forward_cycle_selection_save(slot: str, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.posting_mode import save_forward_selection

    ids = (body or {}).get("target_ids") or (body or {}).get("targets") or []
    cfg = save_forward_selection(slot, ids)
    await _push_state()
    return {
        "status": "ok",
        "target_ids": list(cfg.forwarding.forward_selected_target_ids or []),
    }


@app.post("/account/{slot}/forward-message/cancel")
async def forward_message_cancel(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services.forward_message_service import forward_message_service

    job = await forward_message_service.cancel_job(slot)
    await _push_state()
    return {"status": "ok", "job": job}


@app.post("/account/{slot}/restart")
async def restart_account(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    ok = await manager.restart_account(slot)
    await _push_state()
    return {"status": "restarted" if ok else "error", "slot": slot, **registry.build_ui_state()}


@app.post("/account/{slot}/clear-logs")
async def clear_account_logs(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    await registry.clear_logs(slot)
    await _push_state()
    return {"status": "cleared", "slot": slot, **registry.build_ui_state()}


@app.get("/state")
async def get_state(request: Request):
    return registry.build_ui_state()


@app.get("/account/{slot}/status")
async def account_status(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    return {"status": "ok", **manager.get_status(slot)}


@app.get("/metrics")
async def fleet_metrics():
    from core.fleet_rate_coordinator import fleet_rate_coordinator
    from core.observability.account_metrics import metrics_store

    return {
        "status": "ok",
        "metrics": metrics_store.all_snapshots(),
        "fleet_rate": fleet_rate_coordinator.snapshot(),
    }


@app.get("/metrics/{slot}")
async def account_metrics(slot: str):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.observability.account_metrics import metrics_store

    return {"status": "ok", "metrics": metrics_store.snapshot(slot)}


@app.get("/alerts")
async def fleet_alerts(limit: int = Query(50, ge=1, le=200)):
    from core.observability.alerts import alert_store

    return {"status": "ok", "alerts": alert_store.recent(limit=limit)}


@app.get("/stats/daily")
async def get_daily_stats():
    from core.daily_stats import refresh_daily_stats

    daily_stats, auto_reset = await asyncio.to_thread(
        refresh_daily_stats, list(ACCOUNTS)
    )
    if auto_reset:
        if auto_reset.scope == "global":
            registry.reset_stats_display_counters(None)
        else:
            for slot in auto_reset.account_ids:
                registry.reset_stats_display_counters(slot)
    return {"status": "ok", "daily_stats": daily_stats}


@app.post("/stats/reset", dependencies=[Depends(_require_fleet_admin)])
async def reset_stats(payload: dict | None = None):
    """Reset daily stat counters and live tick display from now. Chats/logs are kept."""
    return await _perform_stats_reset(payload or {})


@app.post("/stats/reset-24h")
async def reset_daily_stats_24h():
    """Alias for global stats reset (backward compatible)."""
    return await _perform_stats_reset({})


async def _perform_stats_reset(payload: dict):
    from core.daily_stats import compute_daily_stats
    from core.send_stats import invalidate_cache
    from core.stats_reset import (
        StatsResetDebounced,
        get_reset_at_iso,
        set_reset_timestamp,
    )
    from core.join_cycle import daily_join_count_for_reset, join_stats_for_ui
    import services.crm_service as crm_service

    scope = (payload.get("scope") or "global").strip().lower()
    account_id = payload.get("account_id")

    if scope == "account":
        if not account_id or account_id not in ACCOUNTS:
            return {"status": "error", "error": "invalid_account"}
    else:
        account_id = None

    reset_slots = [account_id] if account_id else list(ACCOUNTS)
    join_baselines = {
        slot: daily_join_count_for_reset(slot)
        for slot in reset_slots
        if slot
    }

    try:
        ts = set_reset_timestamp(account_id=account_id, join_baselines=join_baselines)
    except StatsResetDebounced:
        return {
            "status": "error",
            "error": "reset_too_soon",
            "message": "Please wait before resetting stats again.",
        }

    invalidate_cache(account_id)
    registry.reset_stats_display_counters(account_id)
    fresh_stats = compute_daily_stats(list(ACCOUNTS))
    reset_scope = account_id or "global"
    account_states_patch = {
        slot: registry.get_worker(slot).state.to_dict()
        for slot in reset_slots
    }

    await event_bus.publish(
        EventType.STATS_RESET,
        reset_scope,
        {
            "reset_timestamp": ts,
            "reset_at": get_reset_at_iso(account_id),
            "account_id": account_id,
            "scope": "account" if account_id else "global",
            "daily_stats": fresh_stats,
            "account_states": account_states_patch,
        },
        push_state=True,
        broadcast_ws=True,
    )

    await broadcast.broadcast({"type": "daily_stats", "daily_stats": fresh_stats})
    await broadcast.broadcast({"type": "crm", "crm": crm_service.build_crm_payload()})

    return {
        "status": "ok",
        "reset_timestamp": ts,
        "reset_at": get_reset_at_iso(account_id),
        "scope": reset_scope,
        "daily_stats": fresh_stats,
        # Join counters only — do not return full UI state (would overwrite client logs).
        "account_states": {
            slot: {"join_stats": join_stats_for_ui(slot)}
            for slot in reset_slots
            if slot
        },
    }


@app.post("/accounts/restore-sessions")
async def restore_sessions():
    """
    Re-read Telethon .session files and rebuild account_info for every slot.
    No OTP needed when session files are valid. Safe to call after deploy/restart.
    """
    info = await registry.refresh_all_info()
    restored = [s for s, v in info.items() if v and v.get("phone")]
    await _push_state()
    return {
        "success": True,
        "restored": restored,
        "count": len(restored),
        "message": (
            f"Restored {len(restored)} account(s) from session files"
            if restored
            else "No valid sessions found — log in with OTP for each account"
        ),
    }


@app.get("/accounts")
async def list_accounts():
    """Account slots configured on this server (use for dashboard before WebSocket connects)."""
    from core.config import ACCOUNTS as _accounts, ACCOUNT_SLOTS as _slots
    from core.account_info_store import load_account_info
    from core.subscription_accounts import compute_subscription_slots, enrich_account_info

    info_map = {
        s: enrich_account_info(s, load_account_info(s))
        for s in _accounts
    }

    return {
        "account_slots": list(_slots),
        "subscription_slots": compute_subscription_slots(info_map),
        "count": len(_slots),
        "code_version": CODE_VERSION,
    }


@app.post("/accounts/provision-slot")
async def provision_account_slot():
    """Add account11+ when all existing slots are logged in."""
    from core.config import ACCOUNT_SLOTS, provision_next_account_slot, sync_accounts_bindings

    slot = provision_next_account_slot()
    sync_accounts_bindings()
    _sync_login_state_slots()
    registry.register_new_slot(slot)
    login_state.setdefault(slot, {"phone": None, "phone_code_hash": None})
    registry.active_account = slot
    await _push_state()
    return {
        "status": "ok",
        "slot": slot,
        "account_slots": list(ACCOUNT_SLOTS),
        "message": f"Added {slot} — log in with phone + OTP below.",
        **registry.build_ui_state(),
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/version")
async def version():
    """Identify exactly which commit is serving this deployment.

    A deployment that cannot say what it is running cannot be verified, and
    cannot be rolled back with confidence. RELEASE_SHA is baked in at image
    build time; "unknown" means the image was built outside the release path.
    """
    return {
        "service": os.getenv("SERVICE_NAME", "teleautomation-messaging"),
        "sha": os.getenv("RELEASE_SHA", "unknown"),
        "built_at": os.getenv("RELEASE_BUILT_AT", "unknown"),
    }


# ── Groups (API-only writes to master list) ─────────────────────────────────

@app.get("/groups")
async def get_groups():
    groups = load_master_groups()
    return {"groups": groups, "total": len(groups)}


@app.get("/groups/removed")
async def get_removed_groups():
    invalid, blocked = set(), set()
    for slot in ACCOUNTS:
        inv, blk = load_account_dead(slot)
        invalid |= inv
        blocked |= blk
    return {"invalid": sorted(invalid), "blocked": sorted(blocked)}


@app.get("/groups/lists")
async def get_group_lists(slot: str | None = None):
    """
    Per-account dead (invalid/blocked) and good (active) group lists.
    cycle_success = groups that succeeded in the current/last worker cycle.
    """
    target = slot if slot in ACCOUNTS else registry.active_account
    if target not in ACCOUNTS:
        target = ACCOUNT_SLOTS[0]

    lists = build_group_lists(target)
    w = registry.get_worker(target)
    st = w.state
    # AccountState stores these per posting mode as campaign_/forwarding_ lists.
    # Bare success_list/failed_list exist only as keys in the snapshot dict that
    # AccountState builds, never as attributes, so reading them off the object
    # raises AttributeError. This endpoint had no caller until Groups Upload was
    # restored, which is why the 500 only appeared once the UI could reach it.
    cycle_success = list(getattr(st, "campaign_success_list", None) or [])
    raw_failed = (
        list(getattr(st, "campaign_failed_list", None) or [])
        or list(getattr(st, "forwarding_failed_list", None) or [])
    )
    cycle_failed = [
        {"group": x.get("group", ""), "reason": x.get("reason", "")}
        for x in raw_failed
        if isinstance(x, dict)
    ]

    return {
        **lists,
        "cycle_success": cycle_success,
        "cycle_success_count": len(cycle_success),
        "cycle_failed": cycle_failed,
        "cycle_failed_count": len(cycle_failed),
    }


@app.get("/groups/health")
async def get_group_health(slot: str | None = None):
    """
    Live classification of one account's assigned groups into:
      healthy, cooling (recently_processed), risky (risky_until), blocked, invalid.
    Always reads fresh from disk (group_intelligence + dead lists + master).
    """
    from core.groups_store import build_group_health

    target = slot if slot in ACCOUNTS else registry.active_account
    if target not in ACCOUNTS:
        target = ACCOUNT_SLOTS[0]
    return build_group_health(target)


@app.get("/groups/total-list")
async def get_total_joined_list():
    """
    Aggregate the joined groups/channels from every logged-in account into a
    single deduped list. Each entry includes which accounts have it joined.

    Strategy: try a string-session scan first (no contention with the running
    worker). If that fails (no string session), fall back to a worker-session
    scan after the worker briefly releases the file lock.
    """
    from core.account_info_store import load_account_info
    from core.dm_string_session import run_with_string_session
    from core.group_assignment import active_slots
    from core.telegram_client import release_session, run_group_operation
    from features.telegram_joined_stats import fetch_joined_dialog_details

    actives = active_slots()
    aggregated: dict[int, dict] = {}
    per_account: dict[str, dict] = {}
    started_at = datetime.now()

    for slot in actives:
        info = load_account_info(slot) or {}
        account_label = (info.get("name") or info.get("username") or info.get("phone") or slot)
        per_account[slot] = {
            "label": account_label,
            "count": 0,
            "error": None,
            "elapsed_ms": 0,
        }
        slot_started = datetime.now()

        async def _op(client):
            return await fetch_joined_dialog_details(client)

        details: list[dict] | None = None
        try:
            scan = await asyncio.wait_for(
                run_with_string_session(slot, fetch_joined_dialog_details, attempts=2),
                timeout=200,
            )
            if isinstance(scan, dict):
                details = list(scan.get("targets") or [])
            elif isinstance(scan, list):
                details = scan
        except Exception as e_ss:
            try:
                await release_session(slot, wait=1.5)
                scan = await asyncio.wait_for(
                    run_group_operation(slot, _op, attempts=2),
                    timeout=200,
                )
                if isinstance(scan, dict):
                    details = list(scan.get("targets") or [])
                elif isinstance(scan, list):
                    details = scan
            except Exception as e_w:
                per_account[slot]["error"] = f"string:{type(e_ss).__name__}; worker:{type(e_w).__name__}: {e_w}"
            finally:
                try:
                    await release_session(slot, wait=0.3)
                except Exception:
                    pass

        per_account[slot]["elapsed_ms"] = int((datetime.now() - slot_started).total_seconds() * 1000)
        if not details:
            continue
        per_account[slot]["count"] = len(details)
        for d in details:
            ent_id = d.get("id")
            if not isinstance(ent_id, int):
                continue
            existing = aggregated.get(ent_id)
            if existing is None:
                aggregated[ent_id] = {
                    "id": ent_id,
                    "type": d.get("type") or "",
                    "name": d.get("name") or "",
                    "username": d.get("username") or "",
                    "link": d.get("link") or "",
                    "members": d.get("members"),
                    "accounts": [slot],
                }
            else:
                if slot not in existing["accounts"]:
                    existing["accounts"].append(slot)
                if not existing.get("name") and d.get("name"):
                    existing["name"] = d["name"]
                if not existing.get("username") and d.get("username"):
                    existing["username"] = d["username"]
                if not existing.get("link") and d.get("link"):
                    existing["link"] = d["link"]
                if existing.get("members") is None and isinstance(d.get("members"), int):
                    existing["members"] = d["members"]

    items = sorted(aggregated.values(), key=lambda x: (x.get("type") or "", (x.get("name") or "").lower()))
    groups_count = sum(1 for x in items if x.get("type") == "group")
    channels_count = sum(1 for x in items if x.get("type") == "channel")
    return {
        "generated_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
        "logged_in_accounts": actives,
        "per_account": per_account,
        "totals": {
            "unique": len(items),
            "groups": groups_count,
            "channels": channels_count,
        },
        "items": items,
    }


@app.get("/groups/health-summary")
async def get_group_health_summary():
    """Fleet-wide rollup of group health across all logged-in accounts."""
    from core.group_assignment import active_slots
    from core.groups_store import build_group_health

    totals = {"healthy": 0, "cooling": 0, "risky": 0, "blocked": 0, "invalid": 0, "assigned": 0}
    per_slot = []
    actives = active_slots()
    for slot in ACCOUNT_SLOTS:
        snap = build_group_health(slot)
        c = snap.get("counts", {})
        for k in totals:
            totals[k] += int(c.get(k, 0))
        per_slot.append({
            "slot": slot,
            "logged_in": slot in actives,
            "counts": c,
        })
    healthy_pct = round(totals["healthy"] / totals["assigned"] * 100, 1) if totals["assigned"] else 0.0
    return {
        "totals": totals,
        "healthy_pct": healthy_pct,
        "logged_in_accounts": len(actives),
        "per_slot": per_slot,
    }


def _parse_uploaded_groups(raw: list) -> tuple[list[str], int]:
    uploaded, seen = [], set()
    skipped_invalid_format = 0
    for g in raw:
        norm = normalize_upload_username(str(g))
        if not norm:
            skipped_invalid_format += 1
            continue
        if not is_valid_group_username(norm):
            skipped_invalid_format += 1
            continue
        key = _normalize_group_name(norm)
        if key not in seen:
            seen.add(key)
            uploaded.append(norm)
    return uploaded, skipped_invalid_format


@app.post("/groups/update")
async def update_groups(payload: dict):
    raw = payload.get("groups", [])
    mode = (str(payload.get("mode") or "merge")).strip().lower()
    if mode not in ("merge", "replace"):
        mode = "merge"

    uploaded, skipped_invalid_format = _parse_uploaded_groups(raw)
    if not uploaded:
        return {
            "success": False,
            "error": "No valid groups found",
            "skipped_invalid_format": skipped_invalid_format,
            "mode": mode,
        }

    ensure_invalid_registry_backfill()
    try:
        master = load_master_groups(strict=True)
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
            "skipped_invalid_format": skipped_invalid_format,
            "mode": mode,
        }
    all_dead = collect_all_dead_for_upload()
    previous_total = len(master)
    old_set = set(master)

    skipped_dead = 0
    if mode == "replace":
        merged = []
        seen_keys: set[str] = set()
        for g in uploaded:
            key = _normalize_group_name(g)
            if key in all_dead:
                skipped_dead += 1
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(g)

        backup_path = None
        if master:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(
                DATA_DIR, f"groups_list_backup_{len(master)}_{ts}.json"
            )
            try:
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(master, f, indent=2)
            except Exception:
                backup_path = None

        save_master_groups(merged)
        new_set = set(merged)
        await _push_state()
        return {
            "success": True,
            "mode": "replace",
            "total": len(merged),
            "previous_total": previous_total,
            "removed_from_old": len(old_set - new_set),
            "kept_from_old": len(old_set & new_set),
            "added_new": len(new_set - old_set),
            "already_existed": 0,
            "skipped_invalid_format": skipped_invalid_format,
            "skipped_dead": skipped_dead,
            "backup_path": backup_path,
            "groups": merged,
        }

    merged = list(master)
    existing_norm = {_normalize_group_name(g): g for g in master}
    added = 0
    for g in uploaded:
        if _normalize_group_name(g) in all_dead:
            skipped_dead += 1
            continue
        key = _normalize_group_name(g)
        if key in existing_norm:
            continue
        merged.append(g)
        existing_norm[key] = g
        added += 1

    save_master_groups(merged)
    await _push_state()
    return {
        "success": True,
        "mode": "merge",
        "total": len(merged),
        "previous_total": previous_total,
        "removed_from_old": 0,
        "added_new": added,
        "already_existed": len(uploaded) - added - skipped_dead,
        "skipped_invalid_format": skipped_invalid_format,
        "skipped_dead": skipped_dead,
        "groups": merged,
    }


# ── Fleet defaults (global forward link / campaign message) ───────────────────

@app.get("/fleet/defaults")
async def fleet_defaults_get():
    from core.fleet_defaults import get_fleet_defaults

    return {"status": "ok", **get_fleet_defaults()}


@app.post("/fleet/defaults")
async def fleet_defaults_post(body: dict | None = None):
    from core.fleet_defaults import get_fleet_defaults, save_fleet_defaults

    payload = body or {}
    saved = save_fleet_defaults(
        forward_source_url=payload.get("forward_source_url"),
        campaign_message=payload.get("campaign_message"),
    )
    if payload.get("campaign_message"):
        from core.message_store import save_message

        save_message(str(payload.get("campaign_message") or "").strip())
    await _push_state()
    return {"status": "ok", **saved}


@app.post("/fleet/apply-forwarding")
async def fleet_apply_forwarding(body: dict | None = None):
    """Enable forwarding + optional t.me link on all logged-in accounts (skips running)."""
    from services.fleet_setup_service import apply_forwarding_bulk

    payload = body or {}
    result = apply_forwarding_bulk(
        registry=registry,
        source_url=payload.get("source_url"),
        use_saved_default=bool(payload.get("use_saved_default")),
        forward_dispatch=str(payload.get("forward_dispatch") or "auto"),
    )
    await _push_state()
    return {"status": "ok", **result, **registry.build_ui_state()}


@app.post("/fleet/apply-campaign")
async def fleet_apply_campaign(body: dict | None = None):
    """Enable campaign + optional message on all logged-in accounts (skips running)."""
    from services.fleet_setup_service import apply_campaign_bulk

    payload = body or {}
    result = apply_campaign_bulk(
        registry=registry,
        message=payload.get("message"),
        use_saved_default=bool(payload.get("use_saved_default")),
    )
    await _push_state()
    return {"status": "ok", **result, **registry.build_ui_state()}


@app.post("/fleet/apply-source-url")
async def fleet_apply_source_url(body: dict | None = None):
    """Apply t.me post link to logged-in accounts without changing mode (skips running)."""
    from services.fleet_setup_service import apply_forward_source_only

    payload = body or {}
    result = apply_forward_source_only(
        registry=registry,
        source_url=payload.get("source_url"),
        use_saved_default=bool(payload.get("use_saved_default")),
    )
    await _push_state()
    return {"status": "ok", **result}


# ── Message ───────────────────────────────────────────────────────────────────

@app.get("/message")
async def get_message(slot: str | None = None):
    if slot and slot in ACCOUNTS:
        return {
            "message": load_message_for_account(slot),
            "slot": slot,
            "rewrite_enabled": MESSAGE_REWRITE_ENABLED,
        }
    return {"message": load_message(), "rewrite_enabled": MESSAGE_REWRITE_ENABLED}


@app.get("/message/preview")
async def message_preview(slot: str, cycle: int = 1):
    if slot not in ACCOUNTS:
        return {"success": False, "error": "Invalid slot"}
    return {"success": True, **preview_cycle_message(slot, max(1, cycle))}


@app.post("/message")
async def update_message(payload: dict):
    text = payload.get("message", "").strip()
    slot = payload.get("slot")
    if not text:
        return {"success": False, "error": "Message cannot be empty"}
    if slot and slot in ACCOUNTS:
        save_message_for_account(slot, text)
    else:
        save_message(text)
    await _push_state()
    return {"success": True, "slot": slot}


# ── Account UI helpers ────────────────────────────────────────────────────────

@app.post("/account/switch")
async def switch_account(payload: dict):
    slot = payload.get("slot")
    if slot not in ACCOUNTS:
        return {"success": False, "error": "Invalid slot"}
    registry.active_account = slot
    await _push_state()
    return {"success": True, "active_account": slot}


@app.get("/account/status")
async def account_status():
    info = await registry.refresh_all_info()
    return {
        "active_account": registry.active_account,
        "account_info": info,
    }


@app.post("/account/refresh-joined")
async def refresh_joined_counts(payload: dict = {}):
    """Scan Telegram dialogs and store joined group/channel counts for one account."""
    slot = (payload.get("slot") or registry.active_account or "").strip()
    if slot not in ACCOUNTS:
        return {"success": False, "error": "Invalid slot"}
    w = registry.get_worker(slot)
    if not w.state.account_info and not load_account_info(slot):
        return {"success": False, "error": f"{slot} not logged in"}
    try:
        was_running = w.state.running
        base_info = w.state.account_info or load_account_info(slot) or {}

        async def _run_refresh() -> None:
            result = await registry.refresh_joined_counts(slot)
            if result:
                await _push_state()

        if was_running:
            asyncio.create_task(_run_refresh())
            info = base_info
        else:
            info = await registry.refresh_joined_counts(slot)
            if info:
                await _push_state()

        if not info:
            return {"success": False, "error": "Could not read joined counts"}
        has_counts = info.get("joined_total") is not None
        resp = {
            "success": True,
            "slot": slot,
            "joined_groups": info.get("joined_groups", 0),
            "joined_channels": info.get("joined_channels", 0),
            "joined_total": info.get("joined_total", 0),
            "joined_updated_at": info.get("joined_updated_at", ""),
        }
        if was_running:
            resp["queued"] = True
            resp["message"] = (
                "Background scan started — On Telegram count updates live via WebSocket"
            )
        elif not has_counts:
            resp["queued"] = True
            resp["message"] = "Scan in progress — count appears shortly"
        if info.get("joined_scan_partial"):
            resp["partial"] = True
            resp["partial_reason"] = info.get("joined_scan_partial_reason") or (
                "Group count may be incomplete — scan timed out; try again"
            )
        return resp
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Login (per-slot isolated state) ───────────────────────────────────────────

def _duplicate_phone_login_response(phone: str, slot: str) -> dict | None:
    """Block the same Telegram number on two dashboard slots."""
    hit = find_logged_in_slot_by_phone(phone, exclude_slot=slot)
    if not hit:
        return None
    existing_slot, info = hit
    return {
        "success": False,
        "error": duplicate_phone_login_message(existing_slot, info),
        "existing_slot": existing_slot,
    }


@app.post("/login/send-otp")
async def send_otp(payload: dict):
    phone = payload.get("phone", "").strip()
    slot = payload.get("slot", "account1")
    if not phone:
        return {"success": False, "error": "Phone number required"}
    _sync_login_state_slots()
    if not _slot_valid(slot):
        return {
            "success": False,
            "error": f"Unknown account slot “{slot}”. Refresh the page, or add the slot again from Accounts.",
        }
    dup = _duplicate_phone_login_response(phone, slot)
    if dup:
        return dup
    try:
        await asyncio.wait_for(_prepare_login_slot(slot), timeout=45.0)

        async def _send_code():
            c = await telegram_client.get_login_client(slot)
            return await c.send_code_request(phone)

        result = await asyncio.wait_for(
            telegram_client.run_login_with_retry(slot, _send_code),
            timeout=55.0,
        )
        client = await telegram_client.get_login_client(slot)
        session_string = ""
        try:
            session_string = client.session.save() or ""
        except Exception:
            pass
        if session_string:
            telegram_client.remember_login_session_string(slot, session_string)
        pending = {
            "phone": phone,
            "phone_code_hash": result.phone_code_hash,
        }
        login_state[slot] = pending
        save_pending(
            slot,
            phone,
            result.phone_code_hash,
            session_string=session_string or None,
        )
        return {"success": True}
    except asyncio.TimeoutError:
        clear_pending(slot)
        await telegram_client.finalize_login_exclusive(slot)
        return {
            "success": False,
            "error": "Telegram login timed out. Wait 10 seconds, then tap Send OTP again.",
        }
    except Exception as e:
        clear_pending(slot)
        await telegram_client.finalize_login_exclusive(slot)
        err = str(e)
        if "database is locked" in err.lower():
            err = "Session file was busy. Wait 10 seconds, then tap Send OTP again."
        elif "flood" in err.lower() or "wait" in err.lower() and "seconds" in err.lower():
            err = f"Telegram rate limit: {err}. Try again later or use a different number."
        return {"success": False, "error": err}


@app.post("/login/verify-otp")
async def verify_otp(payload: dict):
    code = payload.get("code", "").strip()
    slot = (payload.get("slot") or "").strip()
    _sync_login_state_slots()
    if not _slot_valid(slot):
        return {"success": False, "error": "Invalid account slot — refresh the page and try again"}

    ls = _get_login_pending(slot)
    if not ls:
        return {
            "success": False,
            "error": (
                "Login session expired (server reloaded). "
                "Tap ← Back, send OTP again, then verify within a few minutes."
            ),
        }

    phone = ls.get("phone")
    phone_code_hash = ls.get("phone_code_hash")
    if not all([code, phone, phone_code_hash]):
        return {"success": False, "error": "Missing login state — send OTP again"}
    dup = _duplicate_phone_login_response(phone, slot)
    if dup:
        return dup
    try:
        async def _sign_in() -> None:
            client = await telegram_client.get_login_client(slot)
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)

        await telegram_client.run_login_with_retry(slot, _sign_in)

        client = await telegram_client.get_login_client(slot)
        if not await client.is_user_authorized():
            clear_pending(slot)
            await telegram_client.finalize_login_exclusive(slot)
            return {"success": False, "error": "Sign-in failed — send OTP again"}

        async def _get_me():
            c = await telegram_client.get_login_client(slot)
            return await c.get_me()

        me = await telegram_client.run_login_with_retry(slot, _get_me)
        me_phone = str(getattr(me, "phone", None) or phone or "")
        dup_me = _duplicate_phone_login_response(me_phone, slot)
        if dup_me:
            clear_pending(slot)
            await telegram_client.finalize_login_exclusive(slot)
            return dup_me
        await telegram_client.commit_login_session(slot)
        from core.account_info_store import build_info_from_me

        from core.subscription_accounts import enrich_account_info

        info = enrich_account_info(slot, build_info_from_me(me))
        login_state[slot] = {"phone": None, "phone_code_hash": None}
        clear_pending(slot)

        worker_started = await registry.complete_login(slot, info)

        workspace_mode = str(payload.get("workspace_mode") or "").strip().lower()
        if workspace_mode in ("forwarding", "forward"):
            from core.posting_mode import set_posting_mode

            set_posting_mode(
                slot,
                "forwarding",
                forward_dispatch="auto",
                campaign_enabled=False,
                forwarding_enabled=True,
            )
            w = registry.get_worker(slot)
            w._sync_posting_mode_ui()
        elif workspace_mode in ("campaign",):
            from core.posting_mode import set_posting_mode

            set_posting_mode(
                slot,
                "campaign",
                campaign_enabled=True,
                forwarding_enabled=False,
            )
            w = registry.get_worker(slot)
            w._sync_posting_mode_ui()

        await _push_state()

        async def _scan_joined_background() -> None:
            try:
                await registry.refresh_joined_counts(slot)
                await _push_state()
            except Exception:
                pass

        asyncio.create_task(_scan_joined_background())

        return {
            "success": True,
            "name": info["name"],
            "phone": info["phone"],
            "slot": slot,
            "worker_started": worker_started,
        }
    except Exception as e:
        await telegram_client.finalize_login_exclusive(slot)
        err = str(e)
        if "database is locked" in err.lower():
            err = (
                "Telegram session file is busy (another account task was using it). "
                "Wait 10 seconds, tap ← Back, send OTP again, then verify."
            )
        return {"success": False, "error": err}


@app.post("/login/logout")
async def logout(payload: dict = {}):
    slot = (payload.get("slot") or registry.active_account or "").strip()
    if slot not in ACCOUNTS:
        return {"success": False, "error": "Invalid slot"}
    login_state.setdefault(slot, {"phone": None, "phone_code_hash": None})
    try:
        await registry.logout_account(slot)
        login_state[slot] = {"phone": None, "phone_code_hash": None}
        await _push_state()
        return {"success": True, "slot": slot}
    except Exception as e:
        try:
            await registry.logout_account(slot)
            login_state[slot] = {"phone": None, "phone_code_hash": None}
            await _push_state()
        except Exception:
            pass
        return {"success": False, "error": str(e)}


# ── DM Inbox (private chats only — independent of forwarding workers) ─────────

@app.post("/inbox/listeners/refresh")
async def inbox_ensure_listeners():
    """Re-attach Telethon DM listeners (after reload or if live messages stop)."""
    from services.dm_inbox_service import bootstrap_listeners

    await bootstrap_listeners(force=True)
    return {"status": "ok", "message": "DM listeners re-attached"}


@app.post("/inbox/{slot}/sync/{user_id}")
async def inbox_force_sync(slot: str, user_id: int):
    """Pull latest messages from Telegram for one chat (bypasses UI)."""
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.dm_store import get_messages
    from services.dm_inbox_service import sync_conversation_from_telegram

    added = await sync_conversation_from_telegram(slot, user_id, limit=200)
    return {
        "status": "ok",
        "added": len(added),
        "messages": get_messages(slot, user_id),
    }


@app.get("/inbox")
async def inbox_all(
    slot: str | None = Query(None),
    combined: bool = Query(False),
    sync: bool = Query(False),
):
    from services import dm_inbox_service

    if sync:
        for s in ACCOUNTS:
            try:
                await dm_inbox_service.sync_stored_conversations(s)
            except Exception:
                pass

    if slot:
        if slot not in ACCOUNTS:
            return {"status": "error", "message": "Invalid slot"}
        return {"status": "ok", **dm_inbox_service.build_slot_payload(slot)}
    if combined:
        return {
            "status": "ok",
            "combined": True,
            "conversations": dm_inbox_service.get_combined_conversations(),
        }
    return {"status": "ok", **dm_inbox_service.build_all_inboxes()}


@app.get("/inbox/{slot}/messages/{user_id}")
async def inbox_messages(
    slot: str,
    user_id: int,
    sync: bool = Query(True),
):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    import asyncio

    from core.dm_store import get_messages
    from services import dm_inbox_service

    from core.dm_store import load_inbox

    messages = get_messages(slot, user_id)
    if sync:
        try:
            await dm_inbox_service.sync_read_receipts(slot, user_id)
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                dm_inbox_service.sync_conversation_from_telegram(
                    slot, user_id, limit=dm_inbox_service.INBOX_INITIAL_SYNC_LIMIT
                ),
                timeout=30.0,
            )
            messages = get_messages(slot, user_id)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass
        # Only auto-mark-read on the explicit sync path. The fast (sync=0) path
        # is a passive preview; the front-end calls POST /inbox/{slot}/read/{user_id}
        # once the user has actually viewed the chat.
        key = str(user_id)
        had_unread = int(
            load_inbox(slot).get("conversations", {}).get(key, {}).get("unread_count") or 0
        ) > 0
        if had_unread:
            await dm_inbox_service.mark_read(slot, user_id)
    return {"status": "ok", "slot": slot, "user_id": user_id, "messages": messages}


@app.post("/inbox/{slot}/messages/{user_id}/older")
async def inbox_messages_older(
    slot: str,
    user_id: int,
    before_id: int = Query(..., description="Oldest telegram message id already stored"),
    limit: int = Query(100, ge=10, le=200),
):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.dm_store import get_messages
    from services import dm_inbox_service

    if before_id <= 0:
        return {"status": "error", "message": "Invalid before_id"}
    try:
        meta = await dm_inbox_service.sync_older_messages_from_telegram(
            slot,
            user_id,
            before_telegram_id=before_id,
            limit=limit,
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {
        "status": "ok",
        "slot": slot,
        "user_id": user_id,
        "messages": get_messages(slot, user_id),
        **meta,
    }


@app.get("/inbox/{slot}/messages/{user_id}/export")
async def inbox_export_chat(
    slot: str,
    user_id: int,
    format: str = Query("txt", alias="format"),
):
    """Download one stored conversation (txt, csv, or json)."""
    from fastapi import HTTPException
    from fastapi.responses import Response

    if slot not in ACCOUNTS:
        raise HTTPException(status_code=404, detail="Invalid slot")
    from features.inbox_export import export_conversation

    try:
        body, mime, filename = export_conversation(slot, int(user_id), format)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return Response(
        content=body,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.get("/inbox/{slot}/media/{user_id}/{message_id}")
async def inbox_media(slot: str, user_id: int, message_id: int):
    from fastapi import HTTPException

    if slot not in ACCOUNTS:
        raise HTTPException(status_code=404, detail="Invalid slot")
    from services import dm_inbox_service

    hit = await dm_inbox_service.ensure_inbox_media_file(slot, int(user_id), int(message_id))
    if not hit:
        raise HTTPException(status_code=404, detail="Media not found")
    path, mime = hit
    from core.dm_media import mime_for_cached_file

    return FileResponse(path, media_type=mime_for_cached_file(path) or mime)


@app.post("/inbox/{slot}/reply")
async def inbox_reply(slot: str, body: dict, request: Request):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    user_id = body.get("user_id")
    text = body.get("text") or body.get("message") or ""
    # Track who composed this outbound message: "manual" (operator typed
    # from scratch) or "ai_approved" (operator clicked Suggest, then Send).
    # Other values are ignored and fall back to "manual" so callers can't
    # spoof exotic provenance.
    sent_by_raw = (body.get("sent_by") or "manual").strip().lower()
    sent_by = sent_by_raw if sent_by_raw in {"manual", "ai_approved"} else "manual"
    from core import dashboard_auth_vps as dashboard_auth

    operator_name = (
        dashboard_auth.username_from_request_cookies(dict(request.cookies))
        or (body.get("operator_name") or "").strip()
        or "Operator"
    )
    if user_id is None:
        return {"status": "error", "message": "user_id required"}
    channel = (body.get("channel") or "").strip().lower()
    if channel == "whatsapp":
        try:
            from services.whatsapp_dispatch import dispatch_lead_reply
            from services.crm_service import enrich_conversation, get_lead

            result = await dispatch_lead_reply(
                slot,
                int(user_id),
                str(text),
                sent_by=sent_by,
                channel="whatsapp",
            )
            conv = result.get("conversation") or {}
            uid = int(user_id)
            summary = enrich_conversation(
                slot,
                {
                    "user_id": uid,
                    "username": conv.get("username") or "",
                    "name": conv.get("name") or "",
                    "last_message": conv.get("last_message") or "",
                    "last_message_at": conv.get("last_message_at"),
                    "unread_count": conv.get("unread_count") or 0,
                    "phone_e164": conv.get("phone_e164"),
                    "channels": conv.get("channels"),
                    "whatsapp_linked": conv.get("whatsapp_linked"),
                },
            ) if conv else enrich_conversation(
                slot,
                {"user_id": uid, "username": "", "name": "", "unread_count": 0},
            )
            lead = get_lead(slot, uid)
            return {
                "status": "ok",
                "message": result.get("message"),
                "conversation": summary,
                "lead": lead,
                "channel": "whatsapp",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    reply_to_raw = body.get("reply_to_message_id") or body.get("reply_to")
    reply_to_message_id = None
    if reply_to_raw is not None:
        try:
            rid = int(reply_to_raw)
            if rid > 0:
                reply_to_message_id = rid
        except (TypeError, ValueError):
            pass
    try:
        from messaging.message_router import message_router

        result = await message_router.enqueue_dm_send(
            slot,
            int(user_id),
            str(text),
            wait=True,
            sent_by=sent_by,
            operator_name=operator_name,
            reply_to_message_id=reply_to_message_id,
        )
        from services.crm_service import enrich_conversation, get_lead

        conv = result.get("conversation") or {}
        uid = int(user_id)
        summary = enrich_conversation(
            slot,
            {
                "user_id": uid,
                "username": conv.get("username") or "",
                "name": conv.get("name") or "",
                "last_message": conv.get("last_message") or "",
                "last_message_at": conv.get("last_message_at"),
                "unread_count": conv.get("unread_count") or 0,
            },
        )
        lead = get_lead(slot, uid)
        return {
            "status": "ok",
            "message": result.get("message"),
            "conversation": summary,
            "lead": lead,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/inbox/{slot}/reply-media")
async def inbox_reply_media(
    slot: str,
    request: Request,
    user_id: int = Form(...),
    file: UploadFile = File(...),
    caption: str = Form(""),
    reply_to_message_id: str = Form(""),
):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.config import STATE_DIR
    from core.dm_media import OUTBOUND_UPLOAD_MAX_BYTES
    from core import dashboard_auth_vps as dashboard_auth

    operator_name = (
        dashboard_auth.username_from_request_cookies(dict(request.cookies))
        or "Operator"
    )
    reply_to_id = None
    if reply_to_message_id:
        try:
            rid = int(str(reply_to_message_id).strip())
            if rid > 0:
                reply_to_id = rid
        except (TypeError, ValueError):
            pass

    upload_dir = os.path.join(STATE_DIR, slot, "outbound_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = os.path.basename(file.filename or "upload").replace("..", "_")
    temp_path = os.path.join(upload_dir, f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_name}")

    total = 0
    try:
        with open(temp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > OUTBOUND_UPLOAD_MAX_BYTES:
                    raise ValueError("Attachment too large (max 25 MB)")
                out.write(chunk)
    except Exception as e:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return {"status": "error", "message": str(e)}

    try:
        from messaging.message_router import message_router
        from services.crm_service import enrich_conversation, get_lead

        result = await message_router.enqueue_dm_send_media(
            slot,
            int(user_id),
            temp_path,
            caption=str(caption or ""),
            filename=safe_name,
            content_type=file.content_type or "",
            wait=True,
            sent_by="manual",
            operator_name=operator_name,
            reply_to_message_id=reply_to_id,
        )
        conv = result.get("conversation") or {}
        uid = int(user_id)
        summary = enrich_conversation(
            slot,
            {
                "user_id": uid,
                "username": conv.get("username") or "",
                "name": conv.get("name") or "",
                "last_message": conv.get("last_message") or "",
                "last_message_at": conv.get("last_message_at"),
                "unread_count": conv.get("unread_count") or 0,
            },
        )
        lead = get_lead(slot, uid)
        return {
            "status": "ok",
            "message": result.get("message"),
            "conversation": summary,
            "lead": lead,
        }
    except Exception as e:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return {"status": "error", "message": str(e)}


@app.get("/ai/smart-reply/config")
async def ai_smart_reply_get_config():
    from core import ai_smart_reply
    from core.ai_smart_reply_store import get_config

    return {
        "status": "ok",
        "config": get_config(),
        "health": ai_smart_reply.health(),
    }


@app.post("/ai/smart-reply/config")
async def ai_smart_reply_update_config(body: dict):
    from core import ai_smart_reply
    from core.ai_smart_reply_store import update_config

    patch = {k: v for k, v in (body or {}).items() if v is not None}
    cfg = update_config(**patch)
    return {
        "status": "ok",
        "config": cfg,
        "health": ai_smart_reply.health(),
    }


@app.get("/ai/smart-reply/preset/economy")
async def ai_smart_reply_economy_preset_preview():
    from core.karthik_economy_preset import economy_preset_preview

    return {
        "status": "ok",
        "preview": economy_preset_preview(replace_business_prompt=True),
        "estimated_monthly_usd": "15-22",
    }


@app.post("/ai/smart-reply/preset/economy")
async def ai_smart_reply_apply_economy_preset(body: dict | None = None):
    from core import ai_smart_reply
    from core.karthik_economy_preset import apply_economy_preset

    body = body or {}
    replace_prompt = body.get("replace_business_prompt", True)
    if isinstance(replace_prompt, str):
        replace_prompt = replace_prompt.strip().lower() in {"1", "true", "yes"}
    cfg = apply_economy_preset(replace_business_prompt=bool(replace_prompt))
    return {
        "status": "ok",
        "config": cfg,
        "health": ai_smart_reply.health(),
        "message": "Economy preset applied — lower caps, group rewrite off, compact master prompt.",
    }


@app.post("/ai/smart-reply/preset/standard-caps")
async def ai_smart_reply_apply_standard_caps_preset():
    from core import ai_smart_reply
    from core.karthik_economy_preset import apply_standard_caps_preset

    cfg = apply_standard_caps_preset()
    return {
        "status": "ok",
        "config": cfg,
        "health": ai_smart_reply.health(),
        "message": "Standard caps restored (master prompt unchanged).",
    }


@app.post("/ai/smart-reply/catch-up")
async def ai_smart_reply_catch_up(body: dict | None = None):
    """Enqueue Karthik replies for all waiting inbound chats (after outages)."""
    from core import ai_smart_reply

    if not ai_smart_reply.is_enabled():
        return {"status": "error", "message": "AI disabled or API key missing"}
    body = body or {}
    slot = (body.get("slot") or "").strip() or None
    if slot and slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    max_replies = int(body.get("max_replies") or 25)
    result = await ai_smart_reply.catch_up_pending_replies(
        slot=slot,
        force=bool(body.get("force", True)),
        max_replies=max_replies,
    )
    return {"status": "ok", **result}


@app.post("/ai/smart-reply/leads/{slot}/{user_id}/toggle")
async def ai_smart_reply_lead_toggle(slot: str, user_id: int, body: dict):
    """Enable / disable AI auto-reply for a single lead, or reset its stage."""
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core import ai_smart_reply
    from core.ai_smart_reply_store import (
        STAGE_GREETING,
        get_lead_state,
        update_lead_state,
    )

    if "enabled" in (body or {}):
        enabled = bool(body.get("enabled"))
        if enabled:
            state = ai_smart_reply.enable_for_lead(slot, int(user_id))
        else:
            state = ai_smart_reply.disable_for_lead(slot, int(user_id), reason="ui_toggle")
        return {"status": "ok", "lead_state": state}

    if body.get("reset_stage"):
        state = update_lead_state(slot, int(user_id), stage=STAGE_GREETING, qualification={}, escalated=False)
        return {"status": "ok", "lead_state": state}

    return {"status": "ok", "lead_state": get_lead_state(slot, int(user_id))}


@app.get("/ai/smart-reply/leads/{slot}/{user_id}")
async def ai_smart_reply_lead_state(slot: str, user_id: int):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.ai_smart_reply_store import get_lead_state

    return {"status": "ok", "lead_state": get_lead_state(slot, int(user_id))}


@app.post("/ai/smart-reply/assess")
async def ai_smart_reply_assess():
    """Run Karthik through the knowledge assessment battery and persist
    the resulting scorecard.

    Heavy-ish operation: it issues ~8 LLM calls. Run when the operator
    edits the business prompt or wants to re-verify Karthik. Returns
    the same scorecard payload that's persisted under
    config.last_assessment.
    """
    from core import ai_assessment
    from core.ai_smart_reply_store import get_config, save_assessment

    cfg = get_config()
    try:
        result = await ai_assessment.run_assessment(cfg)
    except Exception as e:
        return {"status": "error", "message": f"Assessment failed: {e}"}

    if result.get("status") == "ok":
        save_assessment(result)
    return result


@app.get("/ai/smart-reply/assessment")
async def ai_smart_reply_get_assessment():
    """Return the last persisted assessment scorecard plus the current
    gate state (`approved`/`override`/`blocked`) so the UI can render
    the right banner without doing the policy math itself."""
    from core.ai_smart_reply_store import get_config, is_assessment_approved

    cfg = get_config()
    last = cfg.get("last_assessment")
    return {
        "status":              "ok",
        "approved":            is_assessment_approved(),
        "require_assessment":  cfg.get("require_assessment", True),
        "manual_approval_at":  cfg.get("manual_approval_at"),
        "last_assessment":     last,
    }


@app.post("/ai/smart-reply/manual-approval")
async def ai_smart_reply_set_manual_approval(body: dict):
    """Operator override. `approved=true` lets AI suggestions run even
    when the last assessment was inconclusive. `approved=false` revokes
    the override and re-engages the gate."""
    from core.ai_smart_reply_store import is_assessment_approved, set_manual_approval

    approved = bool(body.get("approved"))
    cfg = set_manual_approval(approved=approved)
    return {
        "status":             "ok",
        "approved":           is_assessment_approved(),
        "manual_approval_at": cfg.get("manual_approval_at"),
    }


@app.post("/inbox/{slot}/ai-reply")
@app.post("/inbox/{slot}/ai-suggestion")
async def inbox_ai_suggestion(slot: str, body: dict):
    """Generate an AI draft reply for the latest inbound message — but DO
    NOT send it. The frontend fills the reply composer with the draft so
    the operator can review, edit, and click Send themselves.

    Both `/ai-reply` and `/ai-suggestion` route here; `/ai-reply` is kept
    as an alias so older clients keep working — they too will now only
    get a suggestion back, never an automatic send.

    Response shape:
        {
          "status": "ok",
          "text":   "<draft>",
          "stage":  "...",
          "confidence": 0.82,
          "ai": True
        }
    """
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    user_id = body.get("user_id")
    if user_id is None:
        return {"status": "error", "message": "user_id required"}
    from core import ai_smart_reply
    from core.dm_store import load_inbox

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    msgs = list(conv.get("messages") or [])
    last_in = next((m for m in reversed(msgs) if m.get("direction") == "in"), None)
    if not last_in:
        return {"status": "error", "message": "No inbound message in this chat"}
    if not ai_smart_reply.is_enabled():
        return {"status": "error", "message": "AI smart-reply is disabled or API key missing"}

    res = await ai_smart_reply.generate_suggestion(
        slot,
        int(user_id),
        user_message_id=last_in.get("id"),
        user_text=last_in.get("text") or "",
    )
    if not res.get("ok"):
        return {"status": "error", "message": res.get("error") or res.get("reason") or "ai_failed", **res}
    return {"status": "ok", **res}


@app.post("/inbox/{slot}/send-location")
async def inbox_send_location(slot: str, body: dict):
    """Send a geo location pin to a DM recipient from the given account slot.

    Body: { user_id: int, latitude: float, longitude: float, accuracy?: float }
    """
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    user_id = body.get("user_id")
    latitude = body.get("latitude")
    longitude = body.get("longitude")
    accuracy = body.get("accuracy")
    if user_id is None:
        return {"status": "error", "message": "user_id required"}
    if latitude is None or longitude is None:
        return {"status": "error", "message": "latitude and longitude required"}
    try:
        from messaging.message_router import message_router

        result = await message_router.enqueue_dm_send_location(
            slot,
            int(user_id),
            float(latitude),
            float(longitude),
            accuracy=float(accuracy) if accuracy is not None else None,
            wait=True,
        )
        from services.crm_service import enrich_conversation, get_lead

        conv = result.get("conversation") or {}
        uid = int(user_id)
        summary = enrich_conversation(
            slot,
            {
                "user_id": uid,
                "username": conv.get("username") or "",
                "name": conv.get("name") or "",
                "last_message": conv.get("last_message") or "",
                "last_message_at": conv.get("last_message_at"),
                "unread_count": conv.get("unread_count") or 0,
            },
        )
        lead = get_lead(slot, uid)
        return {
            "status": "ok",
            "message": result.get("message"),
            "conversation": summary,
            "lead": lead,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.patch("/inbox/{slot}/messages/{user_id}/{message_id}")
async def inbox_edit_message(slot: str, user_id: int, message_id: int, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    text = body.get("text") or body.get("message") or ""
    if not str(text).strip():
        return {"status": "error", "message": "text required"}
    try:
        from services import dm_inbox_service

        result = await dm_inbox_service.run_dm_edit(
            slot, int(user_id), int(message_id), str(text),
        )
        return {
            "status": "ok",
            "message": result.get("message"),
            "conversation": result.get("conversation"),
            "unchanged": bool(result.get("unchanged")),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.delete("/inbox/{slot}/messages/{user_id}/{message_id}")
async def inbox_delete_message(slot: str, user_id: int, message_id: int):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    try:
        from services import dm_inbox_service

        result = await dm_inbox_service.run_dm_delete_message(
            slot, int(user_id), int(message_id),
        )
        return {
            "status": "ok",
            "message_id": result.get("message_id"),
            "conversation": result.get("conversation"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/inbox/{slot}/read/{user_id}")
async def inbox_mark_read(slot: str, user_id: int):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services import crm_service, dm_inbox_service

    uid = int(user_id)
    await dm_inbox_service.mark_read(slot, uid)
    lead = crm_service.get_lead(slot, uid)
    return {
        "status": "ok",
        "slot": slot,
        "user_id": uid,
        "lead": lead,
        "crm": crm_service.build_crm_payload() if lead else None,
    }


@app.get("/inbox/delete-config")
async def inbox_delete_config():
    """Whether chat delete requires INBOX_DELETE_PASSWORD on the server."""
    pwd = (os.environ.get("INBOX_DELETE_PASSWORD") or "").strip()
    return {"status": "ok", "requires_password": bool(pwd)}


@app.delete("/inbox/{slot}/conversation/{user_id}")
async def inbox_delete_conversation(
    slot: str,
    user_id: int,
    body: dict | None = Body(default=None),
):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    expected = (os.environ.get("INBOX_DELETE_PASSWORD") or "").strip()
    if expected:
        got = ""
        if isinstance(body, dict):
            got = str(body.get("password") or "").strip()
        if got != expected:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Incorrect delete password")
    from services import dm_inbox_service

    result = await dm_inbox_service.delete_conversation(slot, int(user_id))
    if result.get("status") != "ok":
        return result
    from services import call_service

    try:
        await broadcast.broadcast({
            "type": "crm",
            "event": "lead_deleted",
            "slot": slot,
            "user_id": int(user_id),
            "crm": call_service.build_crm_payload(),
        })
    except Exception:
        pass
    return result


# ── CRM (lead management on top of inbox) ─────────────────────────────────────

@app.get("/crm/state")
async def crm_state():
    from services import crm_service

    crm_service.sync_leads_from_inbox()
    return {"status": "ok", **crm_service.build_crm_payload()}


@app.get("/crm/leads/{slot}/{user_id}")
async def crm_get_lead(slot: str, user_id: int):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services import crm_service

    lead = crm_service.get_lead_detail(slot, user_id)
    if not lead:
        return {"status": "error", "message": "Lead not found"}
    return {"status": "ok", "lead": lead}


@app.patch("/crm/leads/{slot}/{user_id}")
async def crm_patch_lead(slot: str, user_id: int, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services import crm_service

    kwargs = {}
    if "status" in body:
        kwargs["status"] = body.get("status")
    if "notes" in body:
        kwargs["notes"] = body.get("notes")
    if "reminder_timestamp" in body:
        kwargs["reminder_timestamp"] = body.get("reminder_timestamp")
        kwargs["_has_reminder"] = True
    if body.get("mark_handled"):
        kwargs["mark_handled"] = True
    lead = await crm_service.update_lead(slot, int(user_id), **kwargs)
    return {"status": "ok", "lead": lead, "crm": crm_service.build_crm_payload()}


@app.post("/crm/leads/{slot}/{user_id}/link-phone")
async def crm_link_phone(slot: str, user_id: int, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    phone = body.get("phone") or body.get("phone_e164") or ""
    from core.contact_link_store import link_phone
    from core.dm_store import load_inbox, save_inbox
    from services.crm_service import enrich_conversation

    link = link_phone(slot, int(user_id), str(phone), linked_by="manual")
    if not link:
        return {"status": "error", "message": "Invalid phone number"}

    data = load_inbox(slot)
    key = str(int(user_id))
    conv = (data.get("conversations") or {}).get(key)
    if conv:
        conv["phone_e164"] = link["phone_e164"]
        channels = set(conv.get("channels") or [])
        channels.update({"telegram", "whatsapp"})
        conv["channels"] = sorted(channels)
        data["conversations"][key] = conv
        save_inbox(slot, data)
        summary = enrich_conversation(
            slot,
            {
                "user_id": int(user_id),
                "username": conv.get("username") or "",
                "name": conv.get("name") or "",
                "last_message": conv.get("last_message") or "",
                "last_message_at": conv.get("last_message_at"),
                "unread_count": conv.get("unread_count") or 0,
                "phone_e164": link["phone_e164"],
                "channels": conv.get("channels"),
            },
        )
    else:
        summary = enrich_conversation(
            slot,
            {
                "user_id": int(user_id),
                "phone_e164": link["phone_e164"],
                "channels": ["telegram", "whatsapp"],
            },
        )

    return {"status": "ok", "link": link, "conversation": summary}


@app.post("/crm/leads/{slot}/{user_id}/mark-handled")
async def crm_mark_handled(slot: str, user_id: int):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services import crm_service

    try:
        lead = await crm_service.mark_reply_handled(slot, int(user_id))
        return {"status": "ok", "lead": lead, "crm": crm_service.build_crm_payload()}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@app.post("/crm/leads/{slot}/{user_id}/follow-up")
async def crm_follow_up(slot: str, user_id: int, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services import crm_service

    hours = body.get("hours")
    if hours is None and body.get("preset") == "tomorrow":
        hours = 24.0
    elif hours is None:
        hours = 2.0
    lead = await crm_service.set_follow_up(slot, int(user_id), hours=float(hours))
    return {"status": "ok", "lead": lead, "crm": crm_service.build_crm_payload()}


@app.get("/crm/call-now/options")
async def crm_call_now_options(
    account_id: str = Query(..., alias="account_id"),
    user_id: int = Query(...),
):
    if account_id not in ACCOUNTS:
        return {"status": "error", "message": "Invalid account_id"}
    from services import call_service

    contact = call_service.resolve_contact(account_id, int(user_id))
    return {
        "status": "ok",
        "contact": contact,
        "options": call_service.build_live_call_options(contact),
    }


@app.post("/crm/call-now")
async def crm_call_now(body: dict):
    slot = body.get("account_id") or body.get("slot")
    user_id = body.get("user_id")
    if not slot or slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid account_id"}
    if user_id is None:
        return {"status": "error", "message": "user_id required"}
    call_type = body.get("call_type") or "telegram"
    send_message = body.get("send_message", True)
    from services import call_service, crm_service as _crm

    try:
        result = await call_service.initiate_live_call(
            slot,
            int(user_id),
            call_type=str(call_type),
            send_message=bool(send_message),
        )
        lead = _crm.get_lead_detail(slot, int(user_id))
        return {
            "status": "ok",
            **result,
            "lead": lead,
            "crm": _crm.build_crm_payload(),
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/crm/karthik/block-spam-chats")
async def crm_karthik_block_spam_chats(body: dict | None = None):
    """Karthik spam guard: scan inbox threads and block solicitation/scam chats."""
    body = body or {}
    slot = body.get("account_id") or body.get("slot")
    from services import crm_service
    from services.spam_guard_service import scan_inbox_and_block_spam

    if slot is not None and slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    result = await scan_inbox_and_block_spam(slot=slot)
    return {"status": "ok", "crm": crm_service.build_crm_payload(), **result}


@app.post("/inbox/{slot}/karthik/block-spam/{user_id}")
async def inbox_karthik_block_spam(slot: str, user_id: int):
    """Block the open chat as spam (Karthik guard / operator)."""
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services import crm_service
    from services.spam_guard_service import block_chat_as_spam

    result = await block_chat_as_spam(slot, int(user_id))
    return {"status": "ok", "crm": crm_service.build_crm_payload(), **result}


@app.get("/inbox/{slot}/karthik/spam-check/{user_id}")
async def inbox_karthik_spam_check(slot: str, user_id: int):
    """Classify whether a stored thread looks like inbound spam."""
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from core.dm_store import load_inbox
    from services.spam_guard_service import classify_conversation_spam

    conv = (load_inbox(slot).get("conversations") or {}).get(str(int(user_id))) or {}
    verdict = classify_conversation_spam(slot, conv)
    return {"status": "ok", "slot": slot, "user_id": int(user_id), **verdict}


@app.post("/crm/unblock")
async def crm_unblock(body: dict):
    slot = body.get("account_id") or body.get("slot")
    user_id = body.get("user_id")
    if not slot or slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid account_id"}
    if user_id is None:
        return {"status": "error", "message": "user_id required"}
    from services import block_service, crm_service as _crm

    try:
        result = await block_service.unblock_lead(slot, int(user_id))
        lead = result["lead"]
        await _crm.broadcast_crm_update(slot, int(user_id), lead)
        return {"status": "ok", "lead": lead, "crm": _crm.build_crm_payload()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/crm/schedule-call")
async def crm_schedule_call_body(body: dict):
    """Schedule a call (flat payload: account_id, user_id, scheduled_time, call_type, notes)."""
    slot = body.get("account_id") or body.get("slot")
    user_id = body.get("user_id")
    if not slot or slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid account_id"}
    if user_id is None:
        return {"status": "error", "message": "user_id required"}
    return await _crm_schedule_call_impl(slot, int(user_id), body)


async def _crm_schedule_call_impl(slot: str, user_id: int, body: dict):
    from services import call_service, crm_service as _crm

    scheduled_time = body.get("scheduled_time")
    if not scheduled_time:
        return {"status": "error", "message": "scheduled_time required"}
    call_type = body.get("call_type") or "telegram"
    notes = body.get("notes") or ""
    try:
        call = await call_service.schedule_lead_call(
            slot,
            user_id,
            scheduled_time=str(scheduled_time),
            call_type=str(call_type),
            notes=str(notes),
        )
        lead = _crm.get_lead_detail(slot, user_id)
        return {"status": "ok", "call": call, "lead": lead, "crm": _crm.build_crm_payload()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/crm/leads/{slot}/{user_id}/calls")
async def crm_schedule_call(slot: str, user_id: int, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    return await _crm_schedule_call_impl(slot, int(user_id), body)


@app.post("/crm/leads/{slot}/{user_id}/calls/complete")
async def crm_complete_call(slot: str, user_id: int, body: dict):
    if slot not in ACCOUNTS:
        return {"status": "error", "message": "Invalid slot"}
    from services import call_service, crm_service

    outcome = body.get("outcome_status") or body.get("status")
    call = await call_service.complete_lead_call(
        slot, int(user_id), outcome_status=outcome
    )
    lead = crm_service.get_lead_detail(slot, int(user_id))
    return {"status": "ok", "call": call, "lead": lead, "crm": crm_service.build_crm_payload()}


@app.get("/login/status")
async def login_status():
    slot = registry.active_account
    if slot:
        info = registry.get_worker(slot).state.account_info
        if info:
            return {
                "logged_in": True,
                "name": info["name"],
                "username": info.get("username", ""),
                "phone": info["phone"],
                "slot": slot,
            }
    return {"logged_in": False}


@app.post("/ai/knowledge/query")
async def knowledge_assistant_query(request: Request, body: dict):
    """Read-only, allowlisted natural-language queries over Marketing CRM data."""
    question = str((body or {}).get("question") or "").strip()
    if not question:
        return {"status": "error", "message": "Question is required"}
    if len(question) > 500:
        return {"status": "error", "message": "Question is too long"}
    from core.knowledge_assistant import answer_question
    return await asyncio.to_thread(
        answer_question, question,
        session_id=str((body or {}).get("session_id") or "") or None,
    )


@app.delete("/ai/knowledge/session/{session_id}")
async def knowledge_assistant_session_end(session_id: str):
    from core.knowledge_assistant import end_session
    return {"status": "ok", "ended": end_session(session_id)}


from core.business_compatibility import install_business_compatibility

install_business_compatibility(app)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(STATIC_DIR, "assets")),
        name="assets",
    )

    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}

    @app.get("/")
    async def serve_index():
        return FileResponse(
            os.path.join(STATIC_DIR, "index.html"),
            headers=_NO_CACHE,
        )

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Never serve index.html for API-like paths (avoids JSON parse errors in the UI)
        api_roots = {
            "groups", "account", "accounts", "login", "auth", "message", "start", "stop",
            "state", "health", "ws", "inbox", "crm", "stats", "admin", "ai", "voice",
            "candidates", "data-room", "public", "metrics", "alerts", "push", "analytics",
            "handler-expenses", "handler-salaries", "company-expenses",
            "forward-message", "operator-tasks", "demo-tools", "slot-screenshot", "api",
        }
        first = full_path.split("/")[0] if full_path else ""
        if first in api_roots:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.exists(file_path):
            return FileResponse(file_path)
        return FileResponse(
            os.path.join(STATIC_DIR, "index.html"),
            headers=_NO_CACHE,
        )
