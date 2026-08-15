"""Persistent state for the AI smart-reply system.

Two things live here:

1.  **Global config** (`data/ai_smart_reply.json`) — runtime-tunable settings the
    user controls from the UI: master enable flag, model, WhatsApp CTA link,
    business prompt, per-lead daily reply cap, etc. API key / base URL stay in
    env vars (see `core/ai_smart_reply.py`) so secrets are not stored on disk.

2.  **Per-lead state** (within the same JSON, keyed by `slot:user_id`) — stage
    in the qualification funnel, last reply timestamp, daily reply count,
    extracted qualification facts, and the human-override flag. Lets us throttle
    per lead and resume the conversation across server restarts.

The store is intentionally simple JSON-on-disk (matches the rest of the project)
with a coarse lock — there are at most a few writes per minute even during a
busy day, so this is fine.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from threading import Lock

from core.config import DATA_DIR

_FILE = os.path.join(DATA_DIR, "ai_smart_reply.json")
_lock = Lock()


# ── Stage labels (mirror UI labels exactly) ─────────────────────────────────
STAGE_GREETING = "greeting"
STAGE_QUALIFY = "qualification"
STAGE_VALUE = "value"
STAGE_CTA = "cta"
STAGE_CLOSED = "closed"
VALID_STAGES = {STAGE_GREETING, STAGE_QUALIFY, STAGE_VALUE, STAGE_CTA, STAGE_CLOSED}


# The Karthik business prompt lives outside git (config/karthik/business.md via
# core.karthik.playbooks). If that source tree is absent in a deployment, fall
# back gracefully instead of failing the whole module import — otherwise
# get_config()/update_config() become unusable and every consumer that reads
# runtime settings (payment_upi_id, model, CTA link, …) silently degrades.
try:
    from core.karthik_business_prompt import KARTHIK_BUSINESS_PROMPT
except Exception:
    try:
        from core.karthik.playbooks import get_business_prompt

        KARTHIK_BUSINESS_PROMPT = get_business_prompt()
    except Exception:
        KARTHIK_BUSINESS_PROMPT = ""

from core import staff_directory as _staff

_DEFAULT_BUSINESS_PROMPT = KARTHIK_BUSINESS_PROMPT


def _default_config() -> dict:
    return {
        "enabled": False,
        # Mode controls how the AI interacts with inbound DMs.
        #
        #   "manual"  – AI is completely off the wire. No drafts, no sends.
        #               The operator types every reply themselves.
        #   "suggest" – AI generates DRAFT REPLIES on demand (or proactively
        #               when a message arrives), but NEVER auto-sends. The
        #               operator must click Send to actually deliver.
        #
        # Auto-send mode does not exist. Even when `enabled=True`, AI never
        # sends anything by itself. This is enforced inside the engine
        # (`maybe_schedule_ai_reply` is a no-op) and the worker (it refuses
        # to execute AI_AUTO_REPLY tasks).
        "mode": "manual",
        # OpenAI-compatible model name (works with OpenAI / OpenRouter / Groq).
        "model": "gpt-4o-mini",
        # Persona name the AI uses when introducing itself. Operator can change
        # this from the UI to e.g. "Priya", "Raj" — affects what the assistant
        # says when asked "who are you" or in opening greetings.
        "assistant_name": _staff.persona_name(),
        # CTA destination shared with serious leads.
        "whatsapp_link": _staff.whatsapp("senior_tech"),
        "whatsapp_label": "WhatsApp",
        # Business description injected into the system prompt.
        "business_prompt": _DEFAULT_BUSINESS_PROMPT,
        # Append-only learned knowledge — never replaced when new prompts are added.
        "knowledge_entries": [],
        # Working hours — Karthik auto-replies only inside this window (IST default).
        "work_hours_enabled": False,
        "work_hours_timezone": "Asia/Kolkata",
        "work_hours_start": "09:00",
        "work_hours_end": "21:00",
        "work_hours_offline_message": "I'm currently offline. I'll reply in working hours.",
        # UPI + QR used when leads ask how to pay. Placeholder defaults only —
        # the real values are set in the production config, never in the repo.
        "payment_upi_id": "company@upi",
        "payment_phone_number": "+919000000001",
        "payment_qr_path": "data/payment_qr.png",
        # Human typing simulation before send (seconds).
        "min_delay_seconds": 1,
        "max_delay_seconds": 4,
        "human_pause_minutes": 10,
        "max_replies_per_lead_per_day": 25,
        "max_replies_per_account_per_hour": 30,
        # Conversation length to include in the LLM context.
        "history_messages": 40,
        # If the model returns confidence < this, escalate to human.
        "min_confidence": 0.45,
        # Karthik must pass a knowledge assessment before he's allowed
        # to draft suggestions for real clients. When True, the
        # /ai-suggestion endpoint refuses to run unless the most recent
        # assessment has verdict=="approved" or the operator manually
        # approved the AI override.
        "require_assessment": True,
        # Snapshot of the most recent assessment scorecard (full
        # results, set by core.ai_assessment.run_assessment).
        "last_assessment": None,
        # Last reply-scenario eval run (config/karthik/evals/replies.yaml).
        "last_reply_evals": None,
        # Operator override — if set to a truthy ISO timestamp the AI is
        # considered approved even if `last_assessment` is missing. Use
        # only when you've manually verified Karthik is good to go.
        "manual_approval_at": None,
        # When true (default), Karthik rephrases the group broadcast template
        # each posting cycle. Contact lines stay fixed; falls back to rule-based
        # emoji/bullet shuffle if the API is unavailable.
        "group_rewrite_enabled": True,
        # "economy" | "standard" | null — set by budget presets in karthik_economy_preset.py
        "budget_preset": None,
        "updated_at": None,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict:
    return {
        "config": _default_config(),
        "leads": {},
        "account_throttle": {},
    }


def _load() -> dict:
    from core.db.connection import use_postgres

    if use_postgres():
        from core.db.ai_pg import pg_load as pg_ai_load
        raw = pg_ai_load()
        if not raw:
            return _empty()
        defaults = _default_config()
        cfg = raw.get("config") or {}
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        if not isinstance(cfg.get("knowledge_entries"), list):
            cfg["knowledge_entries"] = []
        raw["config"] = cfg
        raw.setdefault("leads", {})
        raw.setdefault("account_throttle", {})
        return raw
    with _lock:
        if not os.path.exists(_FILE):
            return _empty()
        try:
            with open(_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _empty()
            # Backfill structure for older files.
            defaults = _default_config()
            cfg = data.get("config") or {}
            for k, v in defaults.items():
                cfg.setdefault(k, v)
            if not isinstance(cfg.get("knowledge_entries"), list):
                cfg["knowledge_entries"] = []
            data["config"] = cfg
            data.setdefault("leads", {})
            data.setdefault("account_throttle", {})
            return data
        except (OSError, json.JSONDecodeError):
            return _empty()


def _save(data: dict) -> None:
    from core.db.connection import use_postgres

    if use_postgres():
        from core.db.ai_pg import pg_save as pg_ai_save
        pg_ai_save(data)
        return
    os.makedirs(os.path.dirname(_FILE), exist_ok=True)
    with _lock:
        tmp = _FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _FILE)


# ── Config -------------------------------------------------------------------

def get_config() -> dict:
    return dict(_load()["config"])


def _normalize_knowledge_text(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def get_effective_business_prompt(cfg: dict | None = None) -> str:
    """Base prompt + learned knowledge entries + ops playbook from team chats."""
    cfg = cfg or get_config()
    base = (cfg.get("business_prompt") or "").strip()
    entries = cfg.get("knowledge_entries") or []

    parts: list[str] = [base] if base else []
    if isinstance(entries, list):
        for i, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                continue
            content = (entry.get("content") or "").strip()
            if not content:
                continue
            title = (entry.get("title") or "").strip()
            added = (entry.get("added_at") or "")[:10]
            header = f"--- Learned knowledge #{i}"
            if title:
                header += f": {title}"
            if added:
                header += f" ({added})"
            header += " ---"
            parts.append(f"{header}\n{content}")

    try:
        from core.karthik.playbooks import get_ops_playbook

        ops = get_ops_playbook().strip()
        if ops and not any(ops in p for p in parts):
            parts.append(f"--- Team ops (from handler WhatsApp chats) ---\n{ops}")
    except Exception:
        pass

    return "\n\n".join(parts)


def append_knowledge(
    content: str,
    *,
    title: str | None = None,
    source: str = "ui",
) -> dict:
    """Add new prompt/knowledge without clearing prior entries."""
    text = (content or "").strip()
    if not text:
        raise ValueError("Knowledge content is empty")

    data = _load()
    cfg = dict(data["config"])
    entries = list(cfg.get("knowledge_entries") or [])
    norm = _normalize_knowledge_text(text)

    for entry in entries:
        if _normalize_knowledge_text(entry.get("content") or "") == norm:
            return dict(cfg)

    entry_id = f"k{int(time.time() * 1000)}"
    entries.append({
        "id": entry_id,
        "title": (title or "").strip() or None,
        "content": text,
        "added_at": _now_iso(),
        "source": (source or "ui").strip() or "ui",
    })
    cfg["knowledge_entries"] = entries
    cfg["updated_at"] = _now_iso()
    data["config"] = cfg
    _save(data)
    return dict(cfg)


def remove_knowledge(entry_id: str) -> dict:
    """Remove one learned entry by id (base prompt is untouched)."""
    eid = (entry_id or "").strip()
    if not eid:
        raise ValueError("entry_id required")

    data = _load()
    cfg = dict(data["config"])
    entries = list(cfg.get("knowledge_entries") or [])
    cfg["knowledge_entries"] = [e for e in entries if (e.get("id") or "") != eid]
    cfg["updated_at"] = _now_iso()
    data["config"] = cfg
    _save(data)
    return dict(cfg)


def update_config(**patch) -> dict:
    data = _load()
    cfg = dict(data["config"])
    allowed = set(_default_config().keys())
    for k, v in patch.items():
        if k not in allowed:
            continue
        if v is None:
            continue
        # knowledge_entries is append-only — use append_knowledge() instead.
        if k == "knowledge_entries":
            continue
        cfg[k] = v
    cfg["updated_at"] = _now_iso()
    data["config"] = cfg
    _save(data)
    return dict(cfg)


def save_assessment(payload: dict) -> dict:
    """Persist knowledge assessment scorecard under config.last_assessment."""
    data = _load()
    cfg = dict(data["config"])
    cfg["last_assessment"] = payload
    cfg["manual_approval_at"] = None
    cfg["updated_at"] = _now_iso()
    data["config"] = cfg
    _save(data)
    return dict(cfg)


def save_reply_evals(payload: dict) -> dict:
    """Persist reply scenario eval results under config.last_reply_evals."""
    data = _load()
    cfg = dict(data["config"])
    cfg["last_reply_evals"] = payload
    cfg["updated_at"] = _now_iso()
    data["config"] = cfg
    _save(data)
    return dict(cfg)


def set_manual_approval(*, approved: bool) -> dict:
    """Operator override. `approved=True` lets the AI draft even if
    the most recent assessment did not pass cleanly. `approved=False`
    revokes the override and re-engages the gate."""
    data = _load()
    cfg = dict(data["config"])
    cfg["manual_approval_at"] = _now_iso() if approved else None
    cfg["updated_at"] = _now_iso()
    data["config"] = cfg
    _save(data)
    return dict(cfg)


def is_assessment_approved() -> bool:
    """Single source of truth for the suggestion gate.

    Returns True if the AI is currently cleared to draft replies:
      - require_assessment is False (operator opted out), OR
      - the most recent assessment verdict is "approved", OR
      - the operator set a manual_approval_at timestamp.
    """
    cfg = get_config()
    if not cfg.get("require_assessment", True):
        return True
    if cfg.get("manual_approval_at"):
        return True
    last = cfg.get("last_assessment") or {}
    return (last.get("verdict") == "approved")


# ── Per-lead state -----------------------------------------------------------

def _lead_key(slot: str, user_id: int) -> str:
    return f"{slot}:{int(user_id)}"


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_lead_state(slot: str, user_id: int) -> dict:
    data = _load()
    key = _lead_key(slot, user_id)
    state = data["leads"].get(key)
    if not state:
        return {
            "enabled": True,
            "stage": STAGE_GREETING,
            "qualification": {},
            "last_ai_reply_at": None,
            "reply_count_today": 0,
            "reply_count_total": 0,
            "reply_count_date": _today_str(),
            "escalated": False,
            "last_user_message_id": None,
        }
    # Roll the daily counter if the date changed.
    if state.get("reply_count_date") != _today_str():
        state["reply_count_today"] = 0
        state["reply_count_date"] = _today_str()
    return dict(state)


def update_lead_state(slot: str, user_id: int, **patch) -> dict:
    data = _load()
    key = _lead_key(slot, user_id)
    state = data["leads"].get(key) or get_lead_state(slot, user_id)
    state = dict(state)
    today = _today_str()
    if state.get("reply_count_date") != today:
        state["reply_count_today"] = 0
        state["reply_count_date"] = today
    for k, v in patch.items():
        state[k] = v
    state["updated_at"] = _now_iso()
    data["leads"][key] = state
    _save(data)
    return dict(state)


def record_ai_reply(slot: str, user_id: int, *, stage: str, qualification_patch: dict | None = None) -> dict:
    data = _load()
    key = _lead_key(slot, user_id)
    state = dict(data["leads"].get(key) or get_lead_state(slot, user_id))
    today = _today_str()
    if state.get("reply_count_date") != today:
        state["reply_count_today"] = 0
        state["reply_count_date"] = today
    state["reply_count_today"] = int(state.get("reply_count_today") or 0) + 1
    state["reply_count_total"] = int(state.get("reply_count_total") or 0) + 1
    state["last_ai_reply_at"] = _now_iso()
    if stage in VALID_STAGES:
        state["stage"] = stage
    if qualification_patch:
        current = dict(state.get("qualification") or {})
        for k, v in qualification_patch.items():
            if v not in (None, "", "unknown"):
                current[str(k)] = v
        state["qualification"] = current
    state.setdefault("enabled", True)
    data["leads"][key] = state
    _save(data)
    return dict(state)


def delete_lead_state(slot: str, user_id: int) -> bool:
    data = _load()
    key = _lead_key(slot, user_id)
    if key not in data.get("leads", {}):
        return False
    del data["leads"][key]
    _save(data)
    return True


# ── Account-level throttle (rolling 1h window) -----------------------------

def record_account_reply(slot: str) -> None:
    data = _load()
    now = time.time()
    bucket = list(data["account_throttle"].get(slot) or [])
    cutoff = now - 3600
    bucket = [ts for ts in bucket if float(ts) > cutoff]
    bucket.append(now)
    data["account_throttle"][slot] = bucket
    _save(data)


def account_replies_last_hour(slot: str) -> int:
    data = _load()
    bucket = data["account_throttle"].get(slot) or []
    cutoff = time.time() - 3600
    return sum(1 for ts in bucket if float(ts) > cutoff)
