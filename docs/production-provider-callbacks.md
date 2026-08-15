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
| Payment providers | Operations | No inbound callback found in the code; verification is upload-and-extract, not webhook-driven. **Confirm against the provider account before relying on this** |

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

## Open question for you

Is there a payment provider webhook configured **outside** this codebase — in a
provider dashboard rather than in code? The repository shows an upload-and-verify
flow with no inbound payment callback, but a URL registered directly in a
provider console would not appear here.
