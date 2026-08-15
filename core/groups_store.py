"""Groups list — shared file is written only via API; workers get snapshots."""

import json
import os
import re
import threading
import time
from typing import Iterable, List, Set

from core.config import ACCOUNTS, BASE_DIR, DATA_DIR, GROUPS_FILE, STATE_DIR
from core.group_assignment import groups_for_slot, partition_summary

LEGACY_GROUPS_TXT = os.path.join(BASE_DIR, "groups_list.txt")
INVALID_REGISTRY_FILE = os.path.join(DATA_DIR, "invalid_username_registry.json")
_master_write_lock = threading.Lock()

# Retry blocked groups after this many seconds (admin/broadcast bans may lift).
BLOCKED_GROUP_TTL_SECONDS = 14 * 86400

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,}$")
_HEADER_WORDS = frozenset({
    "username", "user", "group", "groups", "channel", "channels",
    "name", "telegram", "link", "url",
})


def normalize_upload_username(raw: str) -> str:
    """Strip @ and t.me/ prefix; does not validate format."""
    s = (raw or "").strip().lstrip("@")
    if re.match(r"^https?://", s, re.I):
        s = re.sub(r"^https?://t\.me/", "", s, flags=re.I)
    return s


def is_valid_group_username(name: str) -> bool:
    """Reject links, bad chars, headers, and names shorter than 3 chars."""
    if not name or "/" in name:
        return False
    if len(name) < 3 or name.lower() in _HEADER_WORDS:
        return False
    return bool(_USERNAME_RE.match(name))


def load_invalid_registry() -> Set[str]:
    """Usernames removed as invalid (not found) — kept so uploads cannot re-add them."""
    _ensure_dirs()
    if not os.path.exists(INVALID_REGISTRY_FILE):
        return set()
    try:
        with open(INVALID_REGISTRY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {_normalize_group_name(g) for g in data if g}
    except Exception:
        pass
    return set()


def register_invalid_usernames(names: Iterable[str]) -> None:
    """Append Telegram-invalid usernames to the persistent skip registry."""
    batch = [_normalize_group_name(n) for n in names if n]
    if not batch:
        return
    _ensure_dirs()
    with _master_write_lock:
        reg = load_invalid_registry()
        before = len(reg)
        reg.update(batch)
        if len(reg) == before:
            return
        with open(INVALID_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(reg), f, indent=2)


def collect_all_dead_for_upload() -> Set[str]:
    """Union of per-account dead lists + global invalid registry (normalized)."""
    dead = load_invalid_registry()
    for slot in ACCOUNTS:
        inv, blk = load_account_dead(slot)
        dead |= {_normalize_group_name(g) for g in inv | blk}
    return dead


def ensure_invalid_registry_backfill() -> None:
    """One-time sync: per-account invalid files → persistent registry."""
    for slot in ACCOUNTS:
        inv, _ = load_account_dead(slot)
        if inv:
            register_invalid_usernames(inv)


def _ensure_dirs(slot: str | None = None) -> None:
    os.makedirs(os.path.dirname(GROUPS_FILE), exist_ok=True)
    if slot:
        os.makedirs(os.path.join(STATE_DIR, slot), exist_ok=True)


def parse_groups_txt(path: str) -> List[str]:
    """Parse groups_list.txt format (numbered lines)."""
    groups: List[str] = []
    seen: Set[str] = set()
    if not os.path.exists(path):
        return groups
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("=") or line.startswith("---"):
                    continue
                m = re.match(r"^\d+\.\s+(@?)([a-zA-Z0-9_]+)", line)
                if m:
                    name = m.group(2)
                    if name not in seen:
                        seen.add(name)
                        groups.append(name)
                    continue
                m2 = re.match(r"^@?([a-zA-Z0-9_]{3,})$", line)
                if m2:
                    name = m2.group(1)
                    if name not in seen:
                        seen.add(name)
                        groups.append(name)
    except Exception:
        pass
    return groups


def load_master_groups(*, strict: bool = False) -> List[str]:
    """Read-only load of master groups list. strict=True raises on corrupt/invalid file."""
    from core.groups_cache import get_cached_master

    def _load_from_disk() -> List[str]:
        _ensure_dirs()
        if not os.path.exists(GROUPS_FILE):
            return []
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            if strict:
                raise ValueError(f"groups_list.json is invalid JSON: {e}") from e
            return []
        except OSError as e:
            if strict:
                raise ValueError(f"Cannot read groups_list.json: {e}") from e
            return []
        if isinstance(data, list):
            return list(data)
        if strict:
            raise ValueError("groups_list.json must be a JSON array of group usernames")
        return []

    if strict:
        return _load_from_disk()
    return get_cached_master(loader=_load_from_disk)


def ensure_groups_loaded() -> int:
    """
    Load groups into data/groups_list.json from legacy sources if empty.
    Returns total group count.
    """
    _ensure_dirs()
    ensure_invalid_registry_backfill()
    existing = load_master_groups()
    if existing:
        return len(existing)

    legacy_json = os.path.join(BASE_DIR, "groups_list.json")
    if os.path.exists(legacy_json):
        try:
            with open(legacy_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    save_master_groups(data)
                    return len(data)
        except Exception:
            pass

    if os.path.exists(LEGACY_GROUPS_TXT):
        parsed = parse_groups_txt(LEGACY_GROUPS_TXT)
        if parsed:
            save_master_groups(parsed)
            return len(parsed)

    return 0


def save_master_groups(groups: List[str]) -> None:
    """Write master list (API and locked purge path)."""
    from core.groups_cache import set_master_cache

    _ensure_dirs()
    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(groups, f, indent=2)
    set_master_cache(groups)


def _normalize_group_name(name: str) -> str:
    return (name or "").strip().lstrip("@").lower()


def _prune_group_intelligence(slot: str, remove_set: Set[str]) -> None:
    path = os.path.join(STATE_DIR, slot, "group_intelligence.json")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        groups = raw.get("groups") if isinstance(raw, dict) else None
        if not isinstance(groups, dict):
            return
        pruned = {k: v for k, v in groups.items() if _normalize_group_name(k) not in remove_set}
        if len(pruned) == len(groups):
            return
        raw["groups"] = pruned
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)
    except Exception:
        pass


def remove_from_master_groups(names: List[str]) -> dict:
    """
    Permanently remove usernames from the master list (all accounts).
    Thread-safe — safe when multiple workers detect invalid groups in parallel.
    Returns counts: before, after, removed, removed_names.
    """
    if not names:
        return {"before": 0, "after": 0, "removed": 0, "removed_names": []}
    with _master_write_lock:
        remove_set = {_normalize_group_name(n) for n in names if n}
        master = load_master_groups()
        before = len(master)
        kept: List[str] = []
        removed_names: List[str] = []
        for g in master:
            if _normalize_group_name(g) in remove_set:
                removed_names.append(g)
            else:
                kept.append(g)
        if not removed_names:
            return {
                "before": before,
                "after": before,
                "removed": 0,
                "removed_names": [],
            }
        save_master_groups(kept)
        legacy = os.path.join(BASE_DIR, "groups_list.json")
        if os.path.exists(legacy) and os.path.abspath(legacy) != os.path.abspath(GROUPS_FILE):
            try:
                with open(legacy, "w", encoding="utf-8") as f:
                    json.dump(kept, f, indent=2)
            except Exception:
                pass
        for slot in ACCOUNTS:
            invalid, blocked = load_account_dead(slot)
            new_invalid = {g for g in invalid if _normalize_group_name(g) not in remove_set}
            if new_invalid != invalid:
                save_account_dead(slot, new_invalid, blocked)
            _prune_group_intelligence(slot, remove_set)
        return {
            "before": before,
            "after": len(kept),
            "removed": len(removed_names),
            "removed_names": sorted(removed_names, key=str.lower),
        }


def purge_invalid_from_master(names: str | Iterable[str]) -> dict:
    """
    Remove invalid (username not found) groups from master + per-account invalid files.
    Called from workers whenever Telegram reports the username does not exist.
    """
    if isinstance(names, str):
        batch = [names]
    else:
        batch = [n for n in names if n]
    result = remove_from_master_groups(batch)
    if result.get("removed"):
        register_invalid_usernames(result.get("removed_names") or batch)
    return result


def purge_stored_invalid_groups(slot: str) -> int:
    """Legacy API cleanup only. Workers keep invalid usernames account-local."""
    invalid, blocked = load_account_dead(slot)
    if not invalid:
        return 0
    register_invalid_usernames(invalid)
    save_account_dead(slot, invalid, blocked)
    return 0


def groups_readonly_snapshot() -> List[str]:
    """Read-only full master list (legacy). Prefer groups_readonly_snapshot_for_slot."""
    return list(load_master_groups())


def groups_readonly_snapshot_for_slot(slot: str) -> List[str]:
    """This account's slice of the master list — load-balanced, read-only."""
    from core.groups_cache import get_cached_slice

    master = load_master_groups()
    return get_cached_slice(slot, master)


def groups_snapshot() -> List[str]:
    """API/startup use — may import legacy sources once."""
    ensure_groups_loaded()
    return list(load_master_groups())


def _account_dead_file(slot: str, kind: str) -> str:
    _ensure_dirs(slot)
    return os.path.join(STATE_DIR, slot, f"{kind}_groups.json")


def _load_blocked_meta(path: str, *, now: float | None = None) -> dict[str, float]:
    """group -> blocked_at unix timestamp."""
    if not os.path.exists(path):
        return {}
    now = now or time.time()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, list):
        return {str(g): now for g in data if g}
    if isinstance(data, dict):
        if data.get("version") == 2 and isinstance(data.get("groups"), dict):
            return {
                str(g): float(ts)
                for g, ts in data["groups"].items()
                if g and ts is not None
            }
        if "groups" not in data:
            return {
                str(g): float(ts)
                for g, ts in data.items()
                if g not in ("version",) and ts is not None
            }
    return {}


def _active_blocked_meta(meta: dict[str, float], *, now: float | None = None) -> dict[str, float]:
    now = now or time.time()
    ttl = BLOCKED_GROUP_TTL_SECONDS
    return {
        g: ts
        for g, ts in meta.items()
        if now - float(ts) < ttl
    }


def _write_blocked_meta(path: str, meta: dict[str, float]) -> None:
    payload = {
        "version": 2,
        "groups": {g: float(ts) for g, ts in sorted(meta.items())},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_blocked_groups(slot: str) -> Set[str]:
    path = _account_dead_file(slot, "blocked")
    meta = _load_blocked_meta(path)
    active = _active_blocked_meta(meta)
    if len(active) != len(meta):
        _write_blocked_meta(path, active)
    return set(active)


def mark_group_blocked(slot: str, group: str, blocked: Set[str]) -> None:
    """Persist a blocked group with timestamp so it can retry after TTL."""
    if not group:
        return
    blocked.add(group)
    path = _account_dead_file(slot, "blocked")
    meta = _load_blocked_meta(path)
    active = _active_blocked_meta(meta)
    active[group] = time.time()
    _write_blocked_meta(path, active)


def load_account_dead(slot: str) -> tuple[Set[str], Set[str]]:
    """Per-account invalid/blocked sets — fully isolated."""
    invalid_path = _account_dead_file(slot, "invalid")
    invalid: Set[str] = set()
    if os.path.exists(invalid_path):
        try:
            with open(invalid_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    invalid.update(data)
        except Exception:
            pass
    blocked = load_blocked_groups(slot)
    return invalid, blocked


def build_group_lists(slot: str) -> dict:
    """
    Dead = invalid + blocked (per-account, from disk).
    Good/active = master list minus dead for this account.
    """
    master = load_master_groups()
    assigned = groups_for_slot(slot, master)
    invalid, blocked = load_account_dead(slot)
    dead_all = invalid | blocked
    active = [g for g in assigned if g not in dead_all]
    part = partition_summary(slot, master)
    return {
        "slot": slot,
        "total_master": len(master),
        "assigned_count": part["assigned_count"],
        "partition": part,
        "invalid": sorted(invalid),
        "blocked": sorted(blocked),
        "dead": sorted(dead_all),
        "dead_count": len(dead_all),
        "active": active,
        "active_count": len(active),
    }


def save_account_dead(slot: str, invalid: Set[str], blocked: Set[str]) -> None:
    _ensure_dirs(slot)
    invalid_path = _account_dead_file(slot, "invalid")
    with open(invalid_path, "w", encoding="utf-8") as f:
        json.dump(sorted(invalid), f, indent=2)
    blocked_path = _account_dead_file(slot, "blocked")
    meta = _load_blocked_meta(blocked_path)
    active = _active_blocked_meta(meta)
    now = time.time()
    kept = {g: active.get(g, meta.get(g, now)) for g in blocked if g}
    _write_blocked_meta(blocked_path, kept)


def _read_group_intelligence(slot: str) -> dict:
    path = os.path.join(STATE_DIR, slot, "group_intelligence.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data.get("groups", {}) or {}
    except Exception:
        pass
    return {}


def build_group_health(slot: str) -> dict:
    """
    Live classification of this account's assigned groups into health buckets:
      - healthy   : eligible to send right now
      - cooling   : recently_processed (30-min per-group cooldown)
      - risky     : risky_until > now (24h after repeated failures)
      - blocked   : in blocked_groups.json (chat-write-forbidden / kicked / etc.)
      - invalid   : in invalid_groups.json (username not found)

    Reads only from disk (group_intelligence.json + dead lists + master list)
    so it is always current and safe for read-only callers (UI, scripts, API).
    """
    import time as _time

    from core.config import GROUP_RECENT_COOLDOWN_SECONDS

    master = load_master_groups()
    assigned = groups_for_slot(slot, master)
    invalid, blocked = load_account_dead(slot)
    intel = _read_group_intelligence(slot)
    now = _time.time()

    healthy: list[str] = []
    cooling: list[str] = []
    risky: list[str] = []
    blocked_list: list[str] = []
    invalid_list: list[str] = []
    detail: dict[str, dict] = {}

    for g in assigned:
        info = intel.get(g, {}) if isinstance(intel, dict) else {}
        risky_until = info.get("risky_until") if isinstance(info, dict) else None
        last_processed = info.get("last_processed") if isinstance(info, dict) else None
        last_result = info.get("last_result") if isinstance(info, dict) else ""
        score = info.get("score") if isinstance(info, dict) else 0

        bucket = "healthy"
        if g in invalid:
            bucket = "invalid"
        elif g in blocked:
            bucket = "blocked"
        else:
            try:
                if risky_until and float(risky_until) > now:
                    bucket = "risky"
            except (TypeError, ValueError):
                pass
            if bucket == "healthy":
                try:
                    if last_processed and (now - float(last_processed)) < GROUP_RECENT_COOLDOWN_SECONDS:
                        bucket = "cooling"
                except (TypeError, ValueError):
                    pass

        target_list = {
            "healthy": healthy,
            "cooling": cooling,
            "risky": risky,
            "blocked": blocked_list,
            "invalid": invalid_list,
        }[bucket]
        target_list.append(g)
        detail[g] = {
            "bucket": bucket,
            "last_result": last_result or "",
            "score": int(score) if isinstance(score, (int, float)) else 0,
            "last_processed": float(last_processed) if last_processed else 0.0,
            "risky_until": float(risky_until) if risky_until else 0.0,
        }

    counts = {
        "healthy": len(healthy),
        "cooling": len(cooling),
        "risky": len(risky),
        "blocked": len(blocked_list),
        "invalid": len(invalid_list),
        "assigned": len(assigned),
    }

    return {
        "slot": slot,
        "updated_at": now,
        "total_master": len(master),
        "assigned_count": len(assigned),
        "counts": counts,
        "healthy": sorted(healthy),
        "cooling": sorted(cooling),
        "risky": sorted(risky),
        "blocked": sorted(blocked_list),
        "invalid": sorted(invalid_list),
        "detail": detail,
    }


def save_group_health_snapshot(slot: str) -> dict:
    """Compute build_group_health(slot) and persist to data/accounts/<slot>/groups_health.json."""
    snap = build_group_health(slot)
    _ensure_dirs(slot)
    path = os.path.join(STATE_DIR, slot, "groups_health.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2)
    except Exception:
        pass
    return snap
