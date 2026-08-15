# Latent imports of modules that do not exist

Date: 2026-08-16
Found by: the first authenticated walkthrough of hosted staging, then a repo-wide sweep.

Two endpoints returned HTTP 500 in hosted staging. Root-causing them exposed a
whole class of defect: **imports of first-party modules that do not exist**.

A missing module only raises when the importing line actually executes. All of
these sit inside functions, so they stay dormant until one specific endpoint is
called. That is why they survived unit tests, container health checks, the
dual-service contract suite, and the CI staging-stack check — every one of which
passed while these endpoints were broken.

## Counts

| Repository | Missing-module imports |
|---|---:|
| Monolith (production today) | 9 |
| Marketing | 7 |
| Operations | 1 |

Marketing's are a subset of the monolith's. **These are inherited faults, not
split regressions** — production carries the same latent bugs right now.

## Fixed (proven reachable and broken in hosted staging)

| Module | Site | Endpoint | Resolution |
|---|---|---|---|
| `core.ai_group_message` | `core/ai_smart_reply.py` | `GET /ai/smart-reply/config` | guarded; `group_rewrite_ready` degrades to `false` |
| `core.ai_work_hours` | `core/ai_smart_reply.py` | `GET /ai/smart-reply/config` | guarded; `work_hours` degrades to `{"available": false}` |

The same function already guarded `core.ai_llm_gateway` and
`core.karthik_inbox_sweep` with `try/except`; these two were simply missed. The
fix follows the author's existing pattern rather than inventing a new one.

Also fixed alongside them, though a different fault: `main.get_group_lists` read
`state.success_list` and `state.failed_list`, which `AccountState` never defines
as attributes — it exposes `campaign_`/`forwarding_`-prefixed lists and surfaces
the bare names only as keys of its snapshot dict. `/groups/lists` had no caller
until Groups Upload was restored, which is why the fault only became visible
once the UI could reach it.

## Not fixed — inventory only

Deliberately left alone. Each is inherited from the monolith, none was reached
by the hosted walkthrough, and changing them would alter behaviour that cannot
be validated in staging without the corresponding provider.

### Marketing

| Module | Sites |
|---|---|
| `core.ai_llm_gateway` | `core/ai_smart_reply.py:135`, `:6834` — already inside a `try/except` |
| `core.daily_briefing` | `main.py:407` |
| `core.tg_audio_bridge` | `services/tgcalls_service.py` ×6 |
| `core.voice_call_ai` | `services/voice_call_service.py:471` |
| `services.interview_reminder_loop` | `main.py:418` |

### Operations

| Module | Sites |
|---|---|
| `features.web_push` | `services/recruitment_notifications.py:9`, `:16` |

## How to re-run the sweep

Walk every first-party `from`/`import` of `core|services|features|workers|events|messaging|api`
and check whether the module file or package exists. Anything reported is a
`ModuleNotFoundError` waiting for the right request.

## Why this matters for cutover

Voice calls, the daily briefing, interview reminders and Operations' web push
all import modules that are absent. If any of those paths is exercised in
production today it fails the same way. This inventory should be worked through
on its own, with the provider available to verify each fix — not folded into the
split cutover.
