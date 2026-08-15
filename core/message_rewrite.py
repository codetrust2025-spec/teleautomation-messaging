"""
Per-cycle message variation — rewrites the saved template each cycle.

Contact lines (phone, WhatsApp, URLs) are never changed.
Enable/disable via MESSAGE_REWRITE_ENABLED in env or core/config.py.
"""

from __future__ import annotations

import random
import re

from core.config import MESSAGE_REWRITE_ENABLED
from core.message_store import load_message_for_account

_PHONE = re.compile(r"\+?\d[\d\s\-]{8,}\d")
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)

# (regex, alternatives) — applied with random chance per match
_PHRASE_SWAPS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\bStruggling to crack\b", re.I), [
        "Finding it hard to clear",
        "Stuck trying to pass",
        "Having trouble clearing",
    ]),
    (re.compile(r"\binterviews\b", re.I), ["interview rounds", "tech interviews", "job interviews"]),
    (re.compile(r"\bswitch tech domains\b", re.I), [
        "move to a new tech stack",
        "change your tech domain",
        "switch technology tracks",
    ]),
    (re.compile(r"\bWe've got you covered\b", re.I), [
        "We can help",
        "We're here to help",
        "We support you end-to-end",
    ]),
    (re.compile(r"\bEnd-to-end Interview Support\b", re.I), [
        "Full interview support",
        "Complete interview guidance",
        "Interview help from start to offer",
    ]),
    (re.compile(r"\btill you get the job\b", re.I), [
        "until you land the role",
        "until you're placed",
        "through to your offer",
    ]),
    (re.compile(r"\bATS-friendly Resume Building\b", re.I), [
        "ATS-optimized resume building",
        "Resume writing for ATS",
        "Professional ATS resume prep",
    ]),
    (re.compile(r"\bReal-time Work\b", re.I), ["Live project", "On-the-job", "Hands-on work"]),
    (re.compile(r"\bProject Support\b", re.I), ["project guidance", "project help", "delivery support"]),
    (re.compile(r"\bMNC-level Interview Prep\b", re.I), [
        "Enterprise-level interview prep",
        "Top-company interview coaching",
        "MNC-style mock interviews",
    ]),
    (re.compile(r"\bServices:\b"), ["What we offer:", "Includes:", "Support includes:"]),
    (re.compile(r"\bIT Career Support\b", re.I), [
        "IT career coaching",
        "Tech career guidance",
        "Career support for IT",
    ]),
    (re.compile(r"\bSerious candidates only\b", re.I), [
        "Genuine inquiries only",
        "For serious job seekers only",
        "Serious profiles only",
    ]),
    (re.compile(r"\bStill waiting for interview calls\b", re.I), [
        "Still waiting on interview calls",
        "No interview calls yet",
        "Haven't got interview calls",
    ]),
    (re.compile(r"\bInterview Support\b", re.I), [
        "Interview coaching",
        "Interview prep support",
        "Full interview guidance",
    ]),
    (re.compile(r"\bFrom Calls to Offer\b", re.I), [
        "From screening to offer",
        "From calls through to offer",
        "Call to offer support",
    ]),
    (re.compile(r"\bYour competition isn't\b", re.I), [
        "Others are moving ahead",
        "Your peers are already interviewing",
        "The market isn't waiting",
    ]),
]

_CLOSERS = [
    "DM for a quick chat.",
    "Message me for details.",
    "Reach out if you're serious.",
    "Ping me to get started.",
]

_OPENERS = ["🚀", "🌟", "💼", "📢", "✨", "🎯", "🔥"]


def _line_is_protected(line: str) -> bool:
    if _PHONE.search(line) or _URL.search(line):
        return True
    low = line.lower()
    return any(
        k in low
        for k in ("whatsapp", "dm or", "message me", "call ", "tel:", "mailto:")
    )


def _apply_phrase_swaps(text: str, rng: random.Random) -> str:
    out = text
    for pattern, choices in _PHRASE_SWAPS:
        if not pattern.search(out):
            continue
        if rng.random() > 0.55:
            continue

        def _repl(m: re.Match[str]) -> str:
            pick = rng.choice(choices)
            if m.group()[0].isupper() and pick[0].islower():
                return pick[0].upper() + pick[1:]
            return pick

        out = pattern.sub(_repl, out, count=1)
    return out


def _vary_opener(line: str, rng: random.Random) -> str:
    m = re.match(r"^(\s*)(\S+)\s+(.*)$", line)
    if not m or not m.group(2):
        return line
    lead = m.group(2)
    if not any(ord(c) > 0x2600 for c in lead):
        return line
    rest = m.group(3)
    return f"{m.group(1)}{rng.choice(_OPENERS)} {rest}"


def rewrite_message_text(
    base: str,
    *,
    slot: str,
    cycle: int,
) -> str:
    """Return a new variant of *base* for this account cycle (deterministic per slot+cycle)."""
    text = (base or "").strip()
    if not text or not MESSAGE_REWRITE_ENABLED:
        return base

    rng = random.Random((hash(f"{slot}:{cycle}") & 0xFFFFFFFF))

    lines = text.splitlines()
    out: list[str] = []
    bullets: list[str] = []

    def flush_bullets() -> None:
        nonlocal bullets
        if not bullets:
            return
        if len(bullets) > 1 and rng.random() < 0.7:
            rng.shuffle(bullets)
        out.extend(bullets)
        bullets = []

    for i, line in enumerate(lines):
        if _line_is_protected(line):
            flush_bullets()
            out.append(line)
            continue

        stripped = line.strip()
        if stripped.startswith(("•", "-", "*", "·")):
            bullets.append(_apply_phrase_swaps(line, rng))
            continue

        flush_bullets()
        rewritten = _apply_phrase_swaps(line, rng)
        if i == 0 or (not out and not bullets):
            rewritten = _vary_opener(rewritten, rng)
        out.append(rewritten)

    flush_bullets()
    result = "\n".join(out).strip()
    if result and MESSAGE_REWRITE_ENABLED:
        closer = rng.choice(_CLOSERS)
        if closer not in result:
            result = f"{result}\n{closer}"
        batch_tag = rng.choice(["(Active today)", "(Open slots)", "(Limited batch)", ""])
        if batch_tag and batch_tag not in result:
            result = f"{result}\n{batch_tag}"
    return result if result else base


def prepare_cycle_message(slot: str, cycle: int) -> str:
    """Load saved message and return the text to use for this cycle."""
    base = load_message_for_account(slot)
    return rewrite_message_text(base, slot=slot, cycle=cycle)


def preview_cycle_message(slot: str, cycle: int) -> dict:
    """For API/UI — show base vs rewritten without posting."""
    base = load_message_for_account(slot)
    variant = rewrite_message_text(base, slot=slot, cycle=cycle)
    return {
        "enabled": MESSAGE_REWRITE_ENABLED,
        "slot": slot,
        "cycle": cycle,
        "base_length": len(base),
        "variant_length": len(variant),
        "variant_preview": variant[:400] + ("…" if len(variant) > 400 else ""),
        "variant": variant,
    }
