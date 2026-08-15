"""Application constants (read-only at runtime)."""

import logging
import os

logger = logging.getLogger("config")

def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


API_ID = _int_env("TELEGRAM_API_ID", 0)
API_HASH = (os.environ.get("TELEGRAM_API_HASH") or "").strip()


def is_production_deploy() -> bool:
    """True when dashboard auth is enabled (VPS / locked-down deploy)."""
    return bool(os.environ.get("DASHBOARD_PASSWORD", "").strip())


def warn_default_telegram_creds() -> None:
    """Log when production still uses baked-in Telethon API defaults."""
    if not is_production_deploy():
        return
    if not API_ID or not API_HASH:
        logger.warning(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH still use dev defaults — set env vars in production"
        )

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(
    os.environ.get("MARKETING_DATA_DIR")
    or os.environ.get("TELEAUTOMATION_DATA_DIR")
    or os.path.join(BASE_DIR, "data")
)
STATE_DIR = os.path.join(DATA_DIR, "accounts")

GROUPS_FILE = os.path.join(DATA_DIR, "groups_list.json")
MESSAGE_FILE = os.path.join(DATA_DIR, "custom_message.txt")

# Default accounts — override/extend via data/accounts_config.json (no code change for account7+)
_DEFAULT_ACCOUNTS = {
    "account1": "session_account1",
    "account2": "session_account2",
    "account3": "session_account3",
    "account4": "session_account4",
    "account5": "session_account5",
    "account6": "session_account6",
    "account7": "session_account7",
    "account8": "session_account8",
    "account9": "session_account9",
    "account10": "session_account10",
}

ACCOUNTS_CONFIG_FILE = os.path.join(DATA_DIR, "accounts_config.json")


def is_whatsapp_enabled() -> bool:
    """Whether WhatsApp inbox/CRM channel integration is active (VPS may import this)."""
    return os.environ.get("WHATSAPP_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "").strip()
WHATSAPP_BSP = os.environ.get("WHATSAPP_BSP", "interakt").strip().lower()
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_DEFAULT_SLOT = os.environ.get("WHATSAPP_DEFAULT_SLOT", "account1").strip() or "account1"


def _refresh_whatsapp_env_from_file() -> None:
    """Re-read WHATSAPP_* from .env (uvicorn workers may skip dotenv)."""
    env_path = os.path.join(BASE_DIR, ".env")
    try:
        if not os.path.isfile(env_path):
            return
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key.startswith("WHATSAPP_"):
                    os.environ[key] = value
    except OSError:
        pass


def whatsapp_webhook_verify_token() -> str:
    _refresh_whatsapp_env_from_file()
    return os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", WHATSAPP_WEBHOOK_VERIFY_TOKEN).strip()


def whatsapp_api_key() -> str:
    _refresh_whatsapp_env_from_file()
    return os.environ.get("WHATSAPP_API_KEY", WHATSAPP_API_KEY).strip()


def whatsapp_bsp_name() -> str:
    _refresh_whatsapp_env_from_file()
    return os.environ.get("WHATSAPP_BSP", WHATSAPP_BSP).strip().lower()


def _load_accounts() -> dict[str, str]:
    if os.path.exists(ACCOUNTS_CONFIG_FILE):
        try:
            import json

            with open(ACCOUNTS_CONFIG_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and raw:
                return {str(k): str(v) for k, v in raw.items()}
        except Exception:
            pass
    return dict(_DEFAULT_ACCOUNTS)


# slot → Telethon session path prefix (one worker + data/accounts/{slot}/ per key)
ACCOUNTS = _load_accounts()

# Ordered slots for UI and iteration (each maps to an independent asyncio worker)
ACCOUNT_SLOTS = list(ACCOUNTS.keys())


def reload_accounts() -> dict[str, str]:
    """Re-read accounts_config.json into module-level ACCOUNTS / ACCOUNT_SLOTS."""
    global ACCOUNTS, ACCOUNT_SLOTS
    ACCOUNTS = _load_accounts()
    ACCOUNT_SLOTS = list(ACCOUNTS.keys())
    sync_accounts_bindings()
    return ACCOUNTS


def sync_accounts_bindings() -> None:
    """Push reloaded ACCOUNTS into modules that imported it at process startup."""
    import sys

    acc = ACCOUNTS
    slots = ACCOUNT_SLOTS
    for name in (
        "server",
        "services.account_manager",
        "core.telegram_client",
        "core.session_manager",
        "core.account_info_store",
        "core.message_store",
        "services.dm_inbox_service",
        "services.forward_message_service",
        "workers.account_worker",
        "messaging.account_queue",
        "messaging.message_router",
    ):
        mod = sys.modules.get(name)
        if mod is None:
            continue
        if hasattr(mod, "ACCOUNTS"):
            setattr(mod, "ACCOUNTS", acc)
        if hasattr(mod, "ACCOUNT_SLOTS"):
            setattr(mod, "ACCOUNT_SLOTS", slots)


def _next_account_slot_name(accounts: dict[str, str]) -> str:
    nums: list[int] = []
    for key in accounts:
        if key.startswith("account"):
            try:
                nums.append(int(key[7:]))
            except ValueError:
                pass
    return f"account{(max(nums) if nums else 0) + 1}"


def provision_next_account_slot() -> str:
    """Append a new account slot to config and on-disk state dir."""
    import json

    accounts = _load_accounts()
    slot = _next_account_slot_name(accounts)
    session_key = f"session_{slot}"
    accounts[slot] = session_key
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(STATE_DIR, slot), exist_ok=True)
    with open(ACCOUNTS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)
        f.write("\n")
    reload_accounts()
    return slot

# Timing — legacy fixed values (smart engine uses ranges below)
CYCLE_DELAY_SECONDS = 30          # fallback / docs
NO_GROUPS_RETRY_SECONDS = 30      # retry when groups list empty
SEND_DELAY_SECONDS = 15           # fallback

# Smart human-like delays (randomized each action; safety-first, not aggressive)
SEND_DELAY_MIN_SECONDS = 12
SEND_DELAY_MAX_SECONDS = 30
SEND_DELAY_GOOD_MIN_SECONDS = 12
SEND_DELAY_GOOD_MAX_SECONDS = 24
SEND_DELAY_LOW_MIN_SECONDS = 18
SEND_DELAY_LOW_MAX_SECONDS = 38
SEND_DELAY_JITTER_CHANCE = 0.15  # occasional extra pause to break patterns
SEND_DELAY_JITTER_MIN = 5
SEND_DELAY_JITTER_MAX = 12

CYCLE_DELAY_MIN_SECONDS = 20
CYCLE_DELAY_MAX_SECONDS = 40
CYCLE_DELAY_GOOD_MIN_SECONDS = 20
CYCLE_DELAY_GOOD_MAX_SECONDS = 32
CYCLE_DELAY_LOW_MIN_SECONDS = 28
CYCLE_DELAY_LOW_MAX_SECONDS = 55

BATCH_BREAK_GROUPS_MIN = 12
BATCH_BREAK_GROUPS_MAX = 18
BATCH_BREAK_MIN_SECONDS = 90   # 1.5 min
BATCH_BREAK_MAX_SECONDS = 180  # 3 min

# Speed optimization — safe ~2× mode for healthy accounts
SEND_DELAY_FAST_MIN_SECONDS = 6
SEND_DELAY_FAST_MAX_SECONDS = 14
CYCLE_DELAY_FAST_MIN_SECONDS = 5
CYCLE_DELAY_FAST_MAX_SECONDS = 15
BATCH_BREAK_GROUPS_FAST_MIN = 20
BATCH_BREAK_GROUPS_FAST_MAX = 30
BATCH_BREAK_FAST_MIN_SECONDS = 45
BATCH_BREAK_FAST_MAX_SECONDS = 90
BATCH_BREAK_GROUPS_SAFE_MIN = 8
BATCH_BREAK_GROUPS_SAFE_MAX = 12
BATCH_BREAK_SAFE_MIN_SECONDS = 120
BATCH_BREAK_SAFE_MAX_SECONDS = 240
DELAY_JITTER_PCT = 0.15
SPEED_FAST_SUCCESS_RATE = 85.0
SPEED_FAST_MIN_CLEAN_CYCLES = 2
FLOOD_FREE_BOOST_STEP = 0.04
FLOOD_FREE_BOOST_MAX = 0.80

# Skip delays — shorter than send delays for throughput
SKIP_DELAY_MIN_SECONDS = 1
SKIP_DELAY_MAX_SECONDS = 4
SKIP_DELAY_FAST_MIN_SECONDS = 1
SKIP_DELAY_FAST_MAX_SECONDS = 2

# Fast post-join (healthy accounts)
POST_JOIN_DELAY_FAST_MIN_SECONDS = 8
POST_JOIN_DELAY_FAST_MAX_SECONDS = 22

# Group intelligence
RECENT_MESSAGE_LIMIT = 3
GROUP_RECENT_COOLDOWN_SECONDS = 1800   # skip if processed within 30 min
GROUP_RETRY_MAX = 3
RISKY_COOLDOWN_SECONDS = 86400         # 24h deprioritize / skip risky groups

# Flood / rate-limit (avoid 60s wait on every group in one cycle)
FLOOD_COOLDOWN_STREAK = 4          # consecutive small floods → short pause & end cycle
FLOOD_COOLDOWN_MIN_SECONDS = 90    # minimum pause when streak hit (small floods)
FLOOD_COOLDOWN_MAX_SECONDS = 360   # cap pause for streak (~6 min, small floods only)
FLOOD_SMALL_BUFFER_MIN = 2
FLOOD_SMALL_BUFFER_MAX = 8
FLOOD_MEDIUM_PAUSE_MIN_SECONDS = 120   # 2 min
FLOOD_MEDIUM_PAUSE_MAX_SECONDS = 360   # 6 min
FLOOD_HARD_BAN_SECONDS = 3600      # Telegram wait >= 1h → long account pause
FLOOD_ACCOUNT_WAIT_CAP = 172800    # max sleep 48h (then retry; Telegram may extend)
# Stop cycle early on medium floods (avoids stacking → 15h ban)
FLOOD_END_CYCLE_SECONDS = 180      # single FloodWait >= 3m → pause & end cycle
FLOOD_HEALTH_LOW_THRESHOLD = 65    # below this: stricter flood rules
HEALTH_GOOD_THRESHOLD = 70         # adaptive delays: lower range
HEALTH_MEDIUM_THRESHOLD = 50       # adaptive delays: default range
FLOOD_STREAK_MAX_HEALTHY = 4       # small floods in a row before pause (healthy account)
FLOOD_STREAK_MAX_LOW_HEALTH = 1    # one flood ends cycle when health is low

# SQLite session file (Windows) — reduce "database is locked" storms
SESSION_LOCK_RECONNECT_WAIT = 5.0       # disconnect + pause before reconnect (Windows SQLite)
SESSION_LOCK_GROUP_COOLDOWN = 4         # extra seconds after a lock failure
SESSION_LOCK_STREAK_END_CYCLE = 3       # consecutive lock fails → pause cycle
SESSION_LOCK_STREAK_PAUSE = 120         # seconds to rest when lock streak hit

# Self-healing / 24-7 recovery
ERROR_RECOVERY_SECONDS = 30  # legacy fallback
ERROR_RECOVERY_MIN_SECONDS = 15
ERROR_RECOVERY_MAX_SECONDS = 25
STILL_LIMITED_MIN_SECONDS = 30
STILL_LIMITED_MAX_SECONDS = 45
NOT_AUTH_RETRY_SECONDS = 120
FLOOD_WAIT_DEFAULT_SECONDS = 600   # 10 min when flood length unknown
FLOOD_WAIT_MAX_SECONDS = 1800      # 30 min cap before cycle (heavy uses 48h cap separately)
CRASH_RESTART_SECONDS = 5
MAX_LOG_ENTRIES = 500

# Per-cycle rewrite of saved message (synonyms, shuffle bullets; phone/WhatsApp lines unchanged)
MESSAGE_REWRITE_ENABLED = os.getenv("MESSAGE_REWRITE_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Join-group cycle (see core/join_cycle.py + user flowchart)
JOIN_COUNT_THRESHOLD = 100          # stricter min interval when joined_total above this
JOIN_COOLDOWN_SECONDS = 7200        # 2h between new joins when 100+ groups on Telegram
JOIN_DAILY_LIMIT = 15               # max NEW joins per UTC day (10–20 typical)
JOIN_RECENT_WINDOW_SECONDS = 7200   # burst window
JOIN_RECENT_MAX = 3                 # max NEW joins inside window
JOIN_MIN_INTERVAL_SECONDS = 7200    # min gap between successful new joins
JOIN_POST_JOIN_MIN_SECONDS = 20     # wait after join before post
JOIN_POST_JOIN_MAX_SECONDS = 120    # 2 min max
JOIN_FAILURE_STREAK_CAP = 4           # skip group after N join failures
JOIN_FAILURE_BACKOFF_MIN = 600
JOIN_FAILURE_BACKOFF_MAX = 86400

# Telegram membership scan (On Telegram dashboard metric)
MEMBERSHIP_REFRESH_INTERVAL_SECONDS = 300   # background check every 5 min
MEMBERSHIP_STALE_SECONDS = 600              # UI stale after 10 min
MEMBERSHIP_REFRESH_STAGGER_SECONDS = 8      # delay between account scans
MEMBERSHIP_MIN_RETRY_SECONDS = 180          # min gap between scan attempts per slot

# Unified Action Scheduler (UAS)
JOIN_MIN_SCORE_FOR_TRY = -2
JOIN_PRIORITY_SCORE = 3
PRE_JOIN_MIN_SCORE = 5
PRE_JOIN_PROBABILITY = 0.08
UAS_DAILY_HEADROOM_FLOOR = 0.1
UAS_JOIN_SUCCESS_MIN_RATE = 0.3
UAS_MIN_JOIN_ATTEMPTS_FOR_RATE = 2
POST_JOIN_DELAY_GOOD_MIN = 15
POST_JOIN_DELAY_GOOD_MAX = 40
POST_JOIN_DELAY_MED_MIN = 30
POST_JOIN_DELAY_MED_MAX = 80
POST_JOIN_DELAY_LOW_MIN = 60
POST_JOIN_DELAY_LOW_MAX = 120

from core import staff_directory as _staff

DEFAULT_MESSAGE = f"""🔥 Power BI Developer | Data Analyst
💼 Interview Support — Calls to Offer

Still waiting for interview calls? 👇

✅ ATS Resume + Naukri (Power BI / Analyst roles)
✅ Power BI · SQL · DAX · Dashboard prep
✅ Technical + client rounds — cleared with you
✅ Non-IT · Gap · Bench · Fresher — supported
✅ 3 months help after you join
✅ BGV + counter-offer tips

🏆 100+ placed | 💯 No result → No pay

⚠️ Serious only

📞 {_staff.phone_digits('data_lead')}
💬 {_staff.whatsapp('data_lead')}"""
