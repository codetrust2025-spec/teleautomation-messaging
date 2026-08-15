"""
Forward cycle job — user-selected groups, one group at a time (human-like).

Default: manual dispatch from posting_mode (template or t.me source).
Optional legacy auto-tick uses interval_forward separately.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from telethon.errors import (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    UserBannedInChannelError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from core.account_logging import account_log
from core.config import ACCOUNTS, DATA_DIR
from core.forward_message_batch import (
    ForwardBatchSettings,
    load_forward_batch_settings,
    save_forward_batch_settings,
    split_into_batches,
)
from core.posting_mode import (
    SOURCE_TELEGRAM,
    SOURCE_TEMPLATE,
    parse_forward_source_url,
    load_posting_mode,
    is_auto_forward_dispatch,
    save_forward_selection,
)
from core.structured_logging import LogEvent
from core.telegram_forward import native_forward_message, parse_target_ids

OnChange = Callable[[], Awaitable[None]]

MAX_ATTEMPT_LOGS = 80
HUMAN_FORWARD_DELAY_MIN = 2.0
HUMAN_FORWARD_DELAY_MAX = 6.0


def _job_store_path(slot: str) -> str:
    return os.path.join(DATA_DIR, slot, "forward_message_job.json")


def _write_job_file(slot: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_job_store_path(slot)), exist_ok=True)
    tmp = _job_store_path(slot) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, _job_store_path(slot))


def _read_job_file(slot: str) -> dict[str, Any] | None:
    path = _job_store_path(slot)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _job_to_store(job: ForwardMessageJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "slot": job.slot,
        "status": job.status,
        "source_peer": job.source_peer,
        "source_message_id": job.source_message_id,
        "source_label": job.source_label,
        "source_type": job.source_type,
        "message_text": job.message_text,
        "preview": dict(job.preview),
        "targets": list(job.targets),
        "batches": list(job.batches),
        "batch_size": job.batch_size,
        "total_batches": job.total_batches,
        "current_batch": job.current_batch,
        "total": job.total,
        "sent": job.sent,
        "failed": job.failed,
        "skipped": job.skipped,
        "current_target": job.current_target,
        "error": job.error,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "estimated_completion_at": job.estimated_completion_at,
        "settings": dict(job.settings),
        "attempt_logs": list(job.attempt_logs),
    }


def _job_from_store(raw: dict[str, Any]) -> ForwardMessageJob:
    return ForwardMessageJob(
        job_id=str(raw.get("job_id") or ""),
        slot=str(raw.get("slot") or ""),
        status=str(raw.get("status") or "idle"),
        source_peer=str(raw.get("source_peer") or ""),
        source_message_id=int(raw.get("source_message_id") or 0),
        source_label=str(raw.get("source_label") or ""),
        source_type=str(raw.get("source_type") or SOURCE_TELEGRAM),
        message_text=str(raw.get("message_text") or ""),
        preview=dict(raw.get("preview") or {}),
        targets=list(raw.get("targets") or []),
        batches=list(raw.get("batches") or []),
        batch_size=int(raw.get("batch_size") or 100),
        total_batches=int(raw.get("total_batches") or 0),
        current_batch=int(raw.get("current_batch") or 0),
        total=int(raw.get("total") or 0),
        sent=int(raw.get("sent") or 0),
        failed=int(raw.get("failed") or 0),
        skipped=int(raw.get("skipped") or 0),
        current_target=str(raw.get("current_target") or ""),
        error=str(raw.get("error") or ""),
        started_at=float(raw.get("started_at") or 0),
        finished_at=float(raw.get("finished_at") or 0),
        estimated_completion_at=float(raw.get("estimated_completion_at") or 0),
        settings=dict(raw.get("settings") or {}),
        attempt_logs=list(raw.get("attempt_logs") or []),
    )


def _dest_peer(record: dict) -> str | int:
    username = (record.get("username") or "").strip()
    if username:
        return username if username.startswith("@") else f"@{username}"
    ent_id = record.get("id")
    if isinstance(ent_id, int):
        return ent_id
    raise ValueError("no peer for target")


def _target_label(record: dict) -> str:
    user = (record.get("username") or "").strip()
    if user:
        return user if user.startswith("@") else f"@{user}"
    name = (record.get("name") or "").strip()
    if name:
        return name[:80]
    ent_id = record.get("id")
    return str(ent_id) if ent_id is not None else "?"


def _classify_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, FloodWaitError):
        return "flood_wait", f"FloodWait {int(exc.seconds)}s"
    if isinstance(exc, ChatWriteForbiddenError):
        return "permission", "Cannot write to this chat"
    if isinstance(exc, UserBannedInChannelError):
        return "permission", "Banned in channel"
    if isinstance(exc, ChannelPrivateError):
        return "invalid", "Channel private or invalid"
    if isinstance(exc, (UsernameNotOccupiedError, UsernameInvalidError)):
        return "invalid", "Invalid username"
    msg = str(exc).strip() or type(exc).__name__
    low = msg.lower()
    if "slowmode" in low or "slow mode" in low:
        return "slow_mode", msg[:200]
    if "timeout" in low or "network" in low:
        return "network", msg[:200]
    return "error", msg[:200]


@dataclass
class ForwardMessageJob:
    job_id: str
    slot: str
    status: str = "idle"  # idle | running | completed | failed | cancelled
    source_peer: str = ""
    source_message_id: int = 0
    source_label: str = ""
    source_type: str = SOURCE_TELEGRAM
    message_text: str = ""
    preview: dict[str, Any] = field(default_factory=dict)
    targets: list[dict] = field(default_factory=list)
    batches: list[list[dict]] = field(default_factory=list)
    batch_size: int = 100
    total_batches: int = 0
    current_batch: int = 0
    total: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    current_target: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    estimated_completion_at: float = 0.0
    settings: dict[str, Any] = field(default_factory=dict)
    attempt_logs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return self.sent + self.failed + self.skipped

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.processed)

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, round((self.processed / self.total) * 100, 1))

    def _update_eta(self) -> None:
        if self.processed <= 0 or self.started_at <= 0:
            self.estimated_completion_at = 0.0
            return
        elapsed = max(0.1, time.time() - self.started_at)
        rate = self.processed / elapsed
        if rate <= 0:
            self.estimated_completion_at = 0.0
            return
        left = self.remaining / rate
        self.estimated_completion_at = time.time() + left

    def _append_log(
        self,
        group: str,
        result: str,
        *,
        error_code: str = "",
        error_message: str = "",
        batch_num: int = 0,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "account": self.slot,
            "batch": batch_num or self.current_batch,
            "group": group,
            "result": result,
            "error_code": error_code,
            "error_message": error_message,
        }
        self.attempt_logs.append(entry)
        if len(self.attempt_logs) > MAX_ATTEMPT_LOGS:
            self.attempt_logs = self.attempt_logs[-MAX_ATTEMPT_LOGS:]
        level = "success" if result == "sent" else "error" if result == "failed" else "info"
        detail = f"batch {entry['batch']} · {group} · {result}"
        if error_message:
            detail += f" · {error_message}"
        try:
            from services.account_manager import manager

            w = manager.get_worker(self.slot)
            line = account_log(
                self.slot,
                detail,
                level=level,
                event=LogEvent.GENERIC,
                extra={"forward_job": self.job_id, "batch": entry["batch"], "group": group},
            )
            w.state.logs.append(line)
            if len(w.state.logs) > 100:
                w.state.logs = w.state.logs[-100:]
        except Exception:
            pass

    def to_dict(self) -> dict[str, Any]:
        self._update_eta()
        eta_iso = None
        if self.estimated_completion_at > 0:
            eta_iso = datetime.fromtimestamp(
                self.estimated_completion_at, tz=timezone.utc
            ).isoformat()
        started_iso = (
            datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat()
            if self.started_at > 0
            else None
        )
        finished_iso = (
            datetime.fromtimestamp(self.finished_at, tz=timezone.utc).isoformat()
            if self.finished_at > 0
            else None
        )
        return {
            "job_id": self.job_id,
            "slot": self.slot,
            "status": self.status,
            "source_peer": self.source_peer,
            "source_message_id": self.source_message_id,
            "source_label": self.source_label,
            "preview": dict(self.preview),
            "batch_size": self.batch_size,
            "total_batches": self.total_batches,
            "current_batch": self.current_batch,
            "total_selected": self.total,
            "total_processed": self.processed,
            "sent": self.sent,
            "failed": self.failed,
            "skipped": self.skipped,
            "remaining": self.remaining,
            "processed": self.processed,
            "percent": self.percent,
            "current_target": self.current_target,
            "error": self.error,
            "started_at": self.started_at,
            "started_at_iso": started_iso,
            "finished_at": self.finished_at,
            "finished_at_iso": finished_iso,
            "estimated_completion_at": self.estimated_completion_at,
            "estimated_completion_iso": eta_iso,
            "settings": dict(self.settings),
            "attempt_logs": list(self.attempt_logs[-30:]),
            "summary": self._summary_text(),
        }

    def _summary_text(self) -> str:
        if self.status == "running":
            batch_part = ""
            if self.total_batches > 0:
                batch_part = f" · batch {self.current_batch}/{self.total_batches}"
            return f"In progress — {self.processed}/{self.total} ({self.percent}%){batch_part}"
        if self.status == "completed":
            return (
                f"Done — sent {self.sent}, failed {self.failed} of {self.total} "
                f"({self.total_batches} batch{'es' if self.total_batches != 1 else ''})"
            )
        if self.status == "cancelled":
            return f"Cancelled — processed {self.processed}/{self.total} before stop"
        if self.status == "failed":
            return self.error or "Job failed"
        return ""


class ForwardMessageService:
    def __init__(self) -> None:
        self._jobs: dict[str, ForwardMessageJob | None] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._on_change: OnChange | None = None

    def set_on_change(self, cb: OnChange | None) -> None:
        self._on_change = cb

    def recover_jobs_after_restart(self) -> None:
        """Mark interrupted running jobs failed; restore last job snapshot per slot."""
        for slot in ACCOUNTS:
            raw = _read_job_file(slot)
            if not raw:
                continue
            if raw.get("status") == "running":
                raw["status"] = "failed"
                raw["error"] = "Job interrupted by server restart"
                raw["finished_at"] = time.time()
                raw["current_target"] = ""
                _write_job_file(slot, raw)
            job = _job_from_store(raw)
            if job.job_id:
                self._jobs[slot] = job

    def _persist_job(self, job: ForwardMessageJob | None, slot: str) -> None:
        if not job or not slot:
            return
        try:
            _write_job_file(slot, _job_to_store(job))
        except OSError:
            pass

    async def _emit(self) -> None:
        if self._on_change:
            await self._on_change()

    def get_settings(self) -> dict[str, Any]:
        return load_forward_batch_settings().to_dict()

    def save_settings(self, raw: dict | None) -> dict[str, Any]:
        payload = raw or {}
        cfg = ForwardBatchSettings(
            batch_size=int(payload.get("batch_size") or 100),
            delay_min_seconds=float(payload.get("delay_min_seconds") or 0.5),
            delay_max_seconds=float(payload.get("delay_max_seconds") or 1.5),
            batch_pause_seconds=float(payload.get("batch_pause_seconds") or 3),
        )
        return save_forward_batch_settings(cfg).to_dict()

    def get_job(self, slot: str) -> ForwardMessageJob | None:
        return self._jobs.get(slot)

    def job_dict(self, slot: str) -> dict[str, Any]:
        job = self._jobs.get(slot)
        if not job:
            return {"status": "idle", "slot": slot, "settings": self.get_settings()}
        return job.to_dict()

    def all_jobs_dict(self, slots: list[str]) -> dict[str, dict]:
        return {s: self.job_dict(s) for s in slots}

    def _ensure_not_busy(self, slot: str, worker_running: bool) -> None:
        task = self._tasks.get(slot)
        if task and not task.done():
            raise ValueError("A forward cycle is already running for this account")
        if worker_running and is_auto_forward_dispatch(slot):
            raise ValueError(
                "Stop 24/7 auto-forward before starting a manual forward cycle"
            )

    async def resolve_source(
        self,
        slot: str,
        *,
        source_url: str = "",
        source_peer: str = "",
        source_message_id: int = 0,
        worker_running: bool = False,
    ) -> dict[str, Any]:
        self._ensure_not_busy(slot, worker_running)
        peer = (source_peer or "").strip()
        msg_id = int(source_message_id or 0)
        label = ""
        if source_url:
            peer, msg_id, label = parse_forward_source_url(source_url)
        if not peer or msg_id <= 0:
            raise ValueError("Paste a valid t.me post link (e.g. https://t.me/channel/123)")

        preview = await self._fetch_preview(slot, peer, msg_id)
        job = ForwardMessageJob(
            job_id=str(uuid.uuid4())[:8],
            slot=slot,
            status="idle",
            source_peer=peer,
            source_message_id=msg_id,
            source_label=label or preview.get("label") or peer,
            preview=preview,
            settings=self.get_settings(),
        )
        self._jobs[slot] = job
        self._persist_job(job, slot)
        await self._emit()
        return job.to_dict()

    async def list_joined_groups(self, slot: str, *, force_refresh: bool = False) -> dict[str, Any]:
        from core.telegram_client import run_group_operation
        from features.telegram_joined_stats import fetch_joined_dialog_details
        from core.posting_mode import clear_joined_targets_cache, save_joined_targets_cache

        if force_refresh:
            clear_joined_targets_cache(slot)

        async def _op(client):
            return await fetch_joined_dialog_details(client)

        scan = await run_group_operation(slot, _op)
        rows = list(scan.get("targets") or [])
        save_joined_targets_cache(slot, rows)
        return {
            "groups": rows,
            "count": len(rows),
            "partial": bool(scan.get("partial")),
            "partial_reason": str(scan.get("partial_reason") or ""),
        }

    async def start_job(
        self,
        slot: str,
        *,
        source_url: str = "",
        source_peer: str = "",
        source_message_id: int = 0,
        target_ids: list | None = None,
        batch_size: int | None = None,
        worker_running: bool = False,
        use_posting_mode_source: bool = True,
        human_pace: bool = True,
    ) -> dict[str, Any]:
        self._ensure_not_busy(slot, worker_running)

        pm = load_posting_mode(slot)
        fwd_cfg = pm.forwarding

        if human_pace:
            settings = ForwardBatchSettings(
                batch_size=1,
                delay_min_seconds=HUMAN_FORWARD_DELAY_MIN,
                delay_max_seconds=HUMAN_FORWARD_DELAY_MAX,
                batch_pause_seconds=0.0,
            ).normalized()
        else:
            settings = load_forward_batch_settings()
            if batch_size is not None:
                settings = save_forward_batch_settings(
                    ForwardBatchSettings(
                        batch_size=int(batch_size),
                        delay_min_seconds=settings.delay_min_seconds,
                        delay_max_seconds=settings.delay_max_seconds,
                        batch_pause_seconds=settings.batch_pause_seconds,
                    )
                )

        source_type = SOURCE_TELEGRAM
        message_text = ""
        peer = (source_peer or "").strip()
        msg_id = int(source_message_id or 0)
        label = ""

        if source_url:
            peer, msg_id, label = parse_forward_source_url(source_url)
            source_type = SOURCE_TELEGRAM
        elif use_posting_mode_source:
            source_type = (fwd_cfg.source_type or SOURCE_TEMPLATE).strip().lower()
            if source_type == SOURCE_TELEGRAM:
                peer = (fwd_cfg.source_peer or "").strip()
                msg_id = int(fwd_cfg.source_message_id or 0)
                label = (fwd_cfg.source_label or "").strip() or peer
                if not peer or msg_id <= 0:
                    raise ValueError("Set a t.me post in Forwarding setup first")
            else:
                from core.message_rewrite import prepare_cycle_message

                message_text = prepare_cycle_message(slot, 1)
                if not message_text.strip():
                    raise ValueError("Set Message to send in Forwarding setup first")
                label = "Message to send"
        else:
            if not peer or msg_id <= 0:
                existing = self._jobs.get(slot)
                if existing and existing.source_peer and existing.source_message_id:
                    peer = existing.source_peer
                    msg_id = existing.source_message_id
                    label = existing.source_label
                    source_type = existing.source_type or SOURCE_TELEGRAM
                else:
                    raise ValueError("Set a message source (t.me link or template) first")

        if source_type != SOURCE_TEMPLATE and (not peer or msg_id <= 0):
            raise ValueError("Set a valid forward source first")

        ids = parse_target_ids(target_ids)
        if not ids:
            ids = list(fwd_cfg.forward_selected_target_ids or [])
        if not ids:
            raise ValueError("Select at least one group, then click Send")

        save_forward_selection(slot, ids)

        listed = await self.list_joined_groups(slot)
        all_groups = listed.get("groups") or []
        selected = [g for g in all_groups if g.get("id") in ids]
        if not selected:
            raise ValueError("No matching joined groups for selection")

        batches = split_into_batches(selected, settings.batch_size)
        preview: dict[str, Any] = {}
        if source_type == SOURCE_TELEGRAM:
            preview = await self._fetch_preview(slot, peer, msg_id)
        else:
            short = (message_text[:280] + "…") if len(message_text) > 280 else message_text
            preview = {
                "text_preview": short,
                "text": message_text[:2000],
                "label": label,
                "source_type": SOURCE_TEMPLATE,
            }

        job = ForwardMessageJob(
            job_id=str(uuid.uuid4())[:8],
            slot=slot,
            status="running",
            source_peer=peer,
            source_message_id=msg_id,
            source_label=label or peer or "template",
            source_type=source_type,
            message_text=message_text,
            preview=preview,
            targets=selected,
            batches=batches,
            batch_size=settings.batch_size,
            total_batches=len(batches),
            current_batch=0,
            total=len(selected),
            started_at=time.time(),
            settings=settings.to_dict(),
        )
        self._jobs[slot] = job
        self._persist_job(job, slot)
        await self._emit()

        self._tasks[slot] = asyncio.create_task(self._run_job(job, settings))
        return job.to_dict()

    async def cancel_job(self, slot: str) -> dict[str, Any]:
        job = self._jobs.get(slot)
        if job and job.status == "running":
            job.status = "cancelled"
            job.finished_at = time.time()
            job.current_target = ""
        task = self._tasks.get(slot)
        if task and not task.done():
            task.cancel()
        if job:
            self._persist_job(job, slot)
        await self._emit()
        return self.job_dict(slot)

    async def _fetch_preview(self, slot: str, peer: str, message_id: int) -> dict[str, Any]:
        from core.telegram_client import run_group_operation

        async def _op(client):
            msg = await client.get_messages(peer, ids=message_id)
            if not msg:
                raise ValueError("Message not found — check the link and account access")
            text = (getattr(msg, "message", None) or "").strip()
            sender = ""
            try:
                if msg.sender:
                    sender = getattr(msg.sender, "username", None) or getattr(
                        msg.sender, "first_name", None
                    ) or ""
            except Exception:
                pass
            return {
                "message_id": int(msg.id),
                "peer": peer,
                "text": text[:2000],
                "text_preview": (text[:280] + "…") if len(text) > 280 else text,
                "date": msg.date.isoformat() if getattr(msg, "date", None) else None,
                "sender": str(sender),
                "has_media": bool(getattr(msg, "media", None)),
                "label": f"{peer} #{msg.id}",
            }

        return await run_group_operation(slot, _op)

    async def _forward_one(
        self,
        client,
        job: ForwardMessageJob,
        record: dict,
        batch_num: int,
    ) -> None:
        if job.status != "running":
            return

        label = _target_label(record)
        job.current_target = label
        await self._emit()

        try:
            dest = _dest_peer(record)
        except ValueError as exc:
            if job.status != "running":
                return
            job.failed += 1
            job._append_log(label, "failed", error_code="invalid", error_message=str(exc), batch_num=batch_num)
            await self._emit()
            return

        try:
            st = (job.source_type or SOURCE_TELEGRAM).strip().lower()
            if st == SOURCE_TEMPLATE:
                from features.interval_forward import _send_template_one
                from core.account_logging import AccountLogger

                me = await client.get_me()
                text = (job.message_text or "").strip()
                if not text:
                    from core.message_rewrite import prepare_cycle_message

                    text = prepare_cycle_message(job.slot, 1)
                outcome = await _send_template_one(
                    client,
                    dest,
                    text,
                    me.id,
                    AccountLogger(job.slot),
                )
                if job.status != "running":
                    return
                if outcome == "sent":
                    job.sent += 1
                    job._append_log(label, "sent", batch_num=batch_num)
                    try:
                        from core.send_stats import record_send

                        record_send(job.slot, "forward")
                    except Exception:
                        pass
                elif outcome == "skipped":
                    job.skipped += 1
                    job._append_log(label, "skipped", batch_num=batch_num)
                elif isinstance(outcome, tuple) and outcome[0] == "flood":
                    wait_s = min(max(int((outcome[1] or {}).get("seconds", 60)), 1), 300)
                    job.failed += 1
                    job._append_log(
                        label,
                        "failed",
                        error_code="flood_wait",
                        error_message=f"FloodWait {wait_s}s",
                        batch_num=batch_num,
                    )
                else:
                    job.failed += 1
                    job._append_log(label, "failed", batch_num=batch_num)
            else:
                await native_forward_message(
                    client,
                    dest,
                    job.source_peer,
                    job.source_message_id,
                    flood_retries=1,
                )
                if job.status != "running":
                    return
                job.sent += 1
                job._append_log(label, "sent", batch_num=batch_num)
                try:
                    from core.send_stats import record_send

                    record_send(job.slot, "forward")
                except Exception:
                    pass
        except FloodWaitError as e:
            if job.status != "running":
                return
            wait_s = min(max(int(e.seconds), 1), 300)
            job.failed += 1
            job._append_log(
                label,
                "failed",
                error_code="flood_wait",
                error_message=f"FloodWait {wait_s}s (retry exhausted)",
                batch_num=batch_num,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if job.status != "running":
                return
            code, msg = _classify_error(e)
            job.failed += 1
            job._append_log(label, "failed", error_code=code, error_message=msg, batch_num=batch_num)

        await self._emit()

    async def _run_job(self, job: ForwardMessageJob, settings: ForwardBatchSettings) -> None:
        from core.telegram_client import run_group_operation

        slot = job.slot
        dmin = settings.delay_min_seconds
        dmax = settings.delay_max_seconds
        batch_pause = settings.batch_pause_seconds

        async def _op(client):
            for batch_idx, batch in enumerate(job.batches, start=1):
                if job.status != "running":
                    break
                job.current_batch = batch_idx
                await self._emit()

                for i, record in enumerate(batch):
                    if job.status != "running":
                        break
                    await self._forward_one(client, job, record, batch_idx)

                    if job.status != "running":
                        break
                    if i < len(batch) - 1 and dmax > 0:
                        delay = random.uniform(dmin, dmax)
                        await asyncio.sleep(delay)

                if job.status != "running":
                    break
                if batch_idx < job.total_batches and batch_pause > 0:
                    job.current_target = f"Batch {batch_idx} done — pause before batch {batch_idx + 1}"
                    await self._emit()
                    await asyncio.sleep(batch_pause)

        try:
            await run_group_operation(slot, _op)
            if job.status == "running":
                job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
        except Exception as e:
            job.status = "failed"
            job.error = str(e)[:500]
        finally:
            job.current_target = ""
            job.finished_at = time.time()
            job._update_eta()
            self._persist_job(job, slot)
            await self._emit()
            self._tasks.pop(slot, None)


forward_message_service = ForwardMessageService()
