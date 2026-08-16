# Provider callback cutover inventory

Status: **PREPARED — nothing changed.** Re-pointing a live callback is a
production change and requires `APPROVE PRODUCTION CUTOVER`.

Everything currently arrives at `https://teleautomation.online`. After the split
each URL belongs to exactly one service on its own subdomain.

The distinction that matters: **who stores the URL**. If the provider holds it,
it must be re-registered in that provider's console and can fail on its own. If
it is purely inbound, moving the hostname is enough.

---

## Requires provider-side re-registration

These break silently if missed. Nothing errors — traffic simply keeps arriving
at the old hostname, or stops arriving at all.

| Provider | URL now | URL after | Owner | Configured by | If missed |
|---|---|---|---|---|---|
| **Google OAuth** (mailbox connect) | `…online/api/candidate-mailboxes/oauth/google/callback` | `operations.…/api/candidate-mailboxes/oauth/google/callback` | Operations | `GOOGLE_OAUTH_REDIRECT_URI` | Google refuses the consent flow with `redirect_uri_mismatch`. **No new mailbox can be connected.** Existing tokens keep working, so this looks fine until someone adds a mailbox |
| **Gmail Pub/Sub push** | `…online/api/gmail/pubsub/push` | `operations.…/api/gmail/pubsub/push` | Operations | `GMAIL_PUBSUB_TOPIC`, `GMAIL_PUBSUB_VERIFICATION_TOKEN` | Push delivery stops. Ingestion falls back to the ~13.5-minute poll, so mail still arrives but **later than expected** — a slow degradation, not an outage |
| **WhatsApp BSP webhook** | `…online/webhooks/whatsapp` | `marketing.…/webhooks/whatsapp` | Marketing | `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_WEBHOOK_SECRET` | Inbound WhatsApp messages stop arriving entirely. The BSP re-verifies on change, so the verify token must be in place **before** re-registering |

Re-register these **one at a time**, verifying each before starting the next.
Batching them means a failure cannot be attributed.

---

## Public links already issued to people

Not provider-registered, but already sent out and clicked by real users.

| Route | Owner | Configured by | Risk |
|---|---|---|---|
| `/call/join/{join_token}` | Marketing | `PUBLIC_CALL_BASE_URL` | Links already sent point at the apex. Once the apex serves the entry page, **previously issued join links 404** |
| `/voice/join/{join_token}` | Marketing | `PUBLIC_CALL_BASE_URL` | Same |
| `/submit-slot` (public booking) | Operations | `OPERATIONS_PUBLIC_URL` | Any circulated booking link points at the apex |

**Recommended mitigation:** keep a narrow redirect on the apex for exactly these
prefixes — `/call/join/`, `/voice/join/`, `/submit-slot` — forwarding to the
owning subdomain for a deprecation period. This is a handful of `location`
blocks and it prevents already-issued links from breaking.

This is the one place where the apex does more than serve a static page, and it
is a redirect, not a proxy — it does not recombine the applications.

---

## Inbound only — no provider registration

| Item | Owner | Note |
|---|---|---|
| Telegram sessions | Marketing | Telegram does not call us; the client connects outward. **No callback to change.** The risk is the session files themselves — see runbook §6 |
| Web push (VAPID) | Marketing | Subscriptions are held by the browser and bound to the VAPID key, not a URL. **Do not regenerate the key** or every existing subscription is invalidated |
| Ollama / OCR | shared | Outbound only, over the reverse SSH tunnel. Unaffected |
| `/auth/verify-admin` | both | Internal to each app, not external |
| Payment providers | Operations | **There is no payment gateway integration at all.** A repo-wide search for razorpay, stripe, payu, phonepe, paytm, cashfree, instamojo, billdesk and ccavenue returns zero integration code in either project. Payment "proofs" are user-uploaded UPI screenshots parsed by OCR/AI. **There is no payment callback to re-point** |

---

## Ordering

1. Subdomains resolve and hold valid certificates — a provider will reject an
   unreachable or untrusted callback URL.
2. Both services healthy and serving on those hostnames.
3. Re-register the three provider URLs, one at a time, verifying each.
4. Add the apex redirects for already-issued links.
5. Confirm: connect a test mailbox (OAuth), send an inbound WhatsApp message,
   and watch for a Pub/Sub push rather than a poll.

Steps 1 and 2 must be finished first. Registering a callback that does not yet
resolve fails at the provider and often rate-limits retries.

---

---

## Silent-failure mechanisms worth knowing before the window

These were found by reading the handlers rather than the route list, and each
fails without raising anything.

**WhatsApp returns 200 when disabled.** `is_whatsapp_enabled()` defaults to
false when `WHATSAPP_ENABLED` is unset (`core/config.py:66`), and the ingest
route then answers `HTTP 200 {"ignored": "whatsapp_disabled"}`
(`core/whatsapp_api.py:36`). The BSP reads 200 as delivered and **never
retries**, so inbound messages are lost permanently with no error on either
side. The production compose now marks every `WHATSAPP_*` variable required, so
a missing value stops the deploy rather than silently dropping traffic.

**Web push regenerates its own keys.** With no `WEB_PUSH_VAPID_*` in the
environment, `vapid_keys()` falls through to `_generate_vapid_keys()` and
persists a **new** keypair (`features/web_push.py:92-96`). On a fresh volume that
happens automatically and invalidates every existing browser subscription —
independently of the hostname change. Both keys are now required.

**Gmail Pub/Sub push cannot authenticate.** `/api/gmail/pubsub/push` is absent
from `_PUBLIC_EXACT` while `api` is an API root, so an unauthenticated POST from
Google is rejected before reaching the handler
(`core/dashboard_auth_vps.py:41-51`). This is **pre-existing, not a split
regression**, and is currently masked because ingestion is poll-only. It must be
fixed before Pub/Sub push is enabled, or push delivery will fail closed.

**Operations recruitment alerts are already dark.**
`services/recruitment_notifications.py:9,16` imports `features.web_push`, which
does not exist in Operations, and both call sites swallow the `ImportError` with
`except Exception: pass`. Recruitment-detection and mailbox-failure alerts
therefore never fire. Slot and reminder notifications are unaffected — those
correctly route to Marketing via `services/messaging_client.py`. Inherited, and
tracked in `docs/migration/latent-missing-imports.md`.
