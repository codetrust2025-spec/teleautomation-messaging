# Production Go / No-Go

Status at time of writing: **NO-GO** — two hard gates are open. Detail below.

A gate is PASS only with evidence. "Looks fine" is not evidence.

---

## Hard gates

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | STAGING VERIFIED | **PASS** | Marketing 22/0 and Operations 24/0 authenticated walkthroughs; 16/0 hosted checks; 27/0 cross-service; both E2E; backup, restore and rollback all verified on the live hosted stack |
| 2 | Release SHAs fixed | **PASS** | Marketing `8ed392d…`, Operations `0207819…`, monolith rollback `68a28ec…`; both services report theirs at `/version` |
| 3 | CI green on those SHAs | **PASS** | dual-service 27/0, staging stack 15/0, restore and rollback verified |
| 4 | Production dependency audit clean | **PASS** | 0 vulnerabilities, both services |
| 5 | Rollback proven | **PASS** | Marketing rolled back one release on the hosted stack **independently of Operations**, both healthy afterwards |
| 6 | Backup and restore proven | **PASS** | hosted backup → restore into disposable targets; row counts matched; **32 foreign keys survived** |
| 7 | Production DB plan with least privilege | **PASS (prepared)** | `provision_databases.sh` creates dedicated owners, revokes `PUBLIC`, and **proves** each user is denied the other's and the monolith's database |
| 8 | DNS plan | **PASS (prepared)** | two new A records; apex unchanged; TTL lowered 24h ahead |
| 9 | TLS plan | **PASS (prepared)** | certbot via the nginx already on port 80; existing apex certificate untouched; renewal timer already installed |
| 10 | Reverse proxy plan | **PASS (prepared)** | separate site file, own `server_name`s, explicit WebSocket upgrade headers, graceful reload only |
| 11 | Secrets matrix | **PASS (prepared)** | below; all production values regenerated, none reused from staging or the monolith |
| 12 | Monitoring | **PASS (prepared)** | `monitor.sh` covers reachability, release identity, both databases, outbox depth and dead-letters, disk, containers, backup freshness |
| 13 | Cutover procedure with freeze strategy | **PASS (prepared)** | runbook §6, 30-minute budget, 60-minute hard stop |
| 14 | Rollback procedure | **PASS (prepared)** | runbook §9, proxy-first, monolith retained 14 days |
| 15 | Provider callback plan | **PASS (prepared)** | three provider-held URLs identified (WhatsApp, Google OAuth, Gmail Pub/Sub); Telegram needs none; **no payment gateway exists**. Re-registration is manual and remains a cutover action |
| 16 | **Production-shaped migration rehearsal** | **OPEN — BLOCKING** | tooling built and verified against synthetic data; needs a production backup restored to a disposable host, which needs your approval |
| 17 | No critical unresolved defect | **PASS with caveat** | no defect introduced by the split remains open; a class of **inherited** defects is documented and deliberately out of scope |
| 18 | Responsible operator available | **OPEN — yours to confirm** | someone must be present for the window and able to authorise rollback |

**Verdict: NO-GO** on gates 16 and 18.

### Corrected after review

An independent inventory found the first draft of `docker-compose.production.yml`
omitted every provider variable. Three would have failed **silently**:

- `WHATSAPP_*` missing → the ingest route answers `200 {"ignored":
  "whatsapp_disabled"}`, the BSP records delivery and never retries, and inbound
  WhatsApp is lost with no error anywhere
- `WEB_PUSH_VAPID_*` missing → a fresh volume generates a **new** keypair and
  invalidates every existing push subscription
- `MAILBOX_CREDENTIAL_ENCRYPTION_KEY` missing → stored mailbox credentials
  become undecryptable

All are now declared **required** (`${VAR:?}`), so a missing value stops the
deploy instead of degrading quietly. This is why the compose file is reviewed
against handler behaviour and not only against `.env.example`.

---

## Gate 16 — the blocking one

The migration tooling is proven: streaming reads, batched inserts, resumable
checkpoints, FK-aware ordering, idempotent re-runs, reconciliation, and a
fail-closed sanitiser that left **zero of 14 planted values** surviving across
every text and JSONB column.

What has *not* happened is a rehearsal against data shaped like production's:
real row counts, real cardinality, real legacy oddities. Synthetic data has
invented distributions, and those are exactly what break a migration at scale.

To close it I need your approval to:

1. take a read-only `pg_dump` of the production database (349 MB),
2. restore it onto a disposable target,
3. run `sanitize_snapshot.py` over it and verify zero leakage,
4. run the split migration against the sanitised copy and reconcile.

Production is untouched throughout — step 1 is a read. Procedure is in
`docs/sanitized-snapshot-procedure.md`.

Until this passes, the cutover would be the first time the tool sees
production-shaped data, which is not a risk worth taking with candidate records
and payment evidence.

---

## Secrets matrix

No value appears here or in any committed file. Every production value is
**newly generated** — nothing is carried over from staging or the monolith.

| Variable | Marketing | Operations | Category | Production value |
|---|---|---|---|---|
| `DATABASE_URL` | ✓ | ✓ | SECRET | **Must differ.** Points each service at its own database and owner |
| `INTERNAL_SERVICE_TOKEN` | ✓ | ✓ | SHARED SECRET | **Must be identical.** The peers authenticate to each other with it |
| `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` | ✓ | ✓ | SECRET | **Must differ.** Separate credentials per workspace, or one login grants both |
| `DASHBOARD_AUTH_SECRET` | ✓ | ✓ | SECRET | **Must differ.** Shared value would make sessions cross-valid |
| `DASHBOARD_COOKIE_SECURE` | ✓ | ✓ | TUNABLE | `true` — TLS terminates at nginx |
| `MARKETING_DATA_DIR` / `OPERATIONS_DATA_DIR` | ✓ | ✓ | PATH | **Must differ.** Separate volumes; neither mounts the other's |
| `OPERATIONS_INTERNAL_URL` | ✓ | — | URL | `http://operations-api:8000` — private network, not the public hostname |
| `MESSAGING_INTERNAL_URL` | — | ✓ | URL | `http://marketing-api:8000` |
| `OPERATIONS_PUBLIC_URL` | ✓ | ✓ | URL | `https://operations.teleautomation.online` |
| `MARKETING_PUBLIC_URL` / `PUBLIC_BASE_URL` | ✓ | ✓ | URL | `https://marketing.teleautomation.online` |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | ✓ | — | PROVIDER CREDENTIAL | Carried from the monolith — they identify the same Telegram application |
| `WEB_PUSH_VAPID_*` | ✓ | — | PROVIDER CREDENTIAL | Carried; regenerating invalidates every existing browser subscription |
| `WHATSAPP_*` | ✓ | — | PROVIDER CREDENTIAL | Carried; see the callback inventory |
| `MAILBOX_CREDENTIAL_ENCRYPTION_KEY` | — | ✓ | SECRET | **Carried, not regenerated** — it decrypts stored mailbox credentials, and a new key makes them unreadable |
| `GMAIL_PUBSUB_*`, `GOOGLE_OAUTH_REDIRECT_URI` | — | ✓ | PROVIDER CREDENTIAL / URL | Redirect URI must move to the Operations hostname |
| `TELEAUTOMATION_SAFE_UI_MODE` | ✓ | ✓ | TUNABLE | `false` in production — staging runs `true` |
| `OLLAMA_*`, `OCR_*`, `AI_*` | ✓ | ✓ | TUNABLE | Carried |

Two that must **not** be regenerated, and would cause silent data loss if they
were: `MAILBOX_CREDENTIAL_ENCRYPTION_KEY` (stored mailbox credentials become
undecryptable) and `WEB_PUSH_VAPID_*` (every existing push subscription is
invalidated).

`.env.production` is `0600`, outside the repository, and matched by the `.env.*`
gitignore rule.

---

## What "PASS (prepared)" means

The artefact exists, is reviewable, and encodes its own safety checks — but has
not been run against production, because running it *is* the cutover. Each was
exercised as far as it can be without touching production:

- the compose stack is the staging stack that passed verification, with
  production hostnames and different ports
- the nginx template mirrors the staging one, whose WebSocket handling is proven
- `provision_databases.sh` proves isolation itself and exits non-zero on failure
- `monitor.sh` is read-only by construction
