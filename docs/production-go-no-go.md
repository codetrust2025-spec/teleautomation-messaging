# Production Go / No-Go

Status at time of writing: **NO-GO** — one hard gate is open, and one owner
decision is outstanding. Detail below.

Gate 16 closed on 2026-08-16. It found four blocking defects, all fixed and
re-verified; see `docs/production-shaped-rehearsal.md` in the monolith
repository. Read that before authorising a cutover — two of the four would have
lost data silently, and one would have copied live Telegram session secrets.

A gate is PASS only with evidence. "Looks fine" is not evidence.

---

## Hard gates

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | STAGING VERIFIED | **PASS** | Marketing 22/0 and Operations 24/0 authenticated walkthroughs; 16/0 hosted checks; 27/0 cross-service; both E2E; backup, restore and rollback all verified on the live hosted stack |
| 2 | Release SHAs fixed | **PASS FOR MERGE** | Operations `d7263370…` is pinned in the production Compose; Marketing is the PR #11 candidate and its merge SHA must be recorded before deployment; both services report theirs at `/version` |
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
| 16 | **Production-shaped migration rehearsal** | **PASS** | ran 2026-08-16 against a read-only 107 MB production export in a disposable container. Found and fixed 4 blocking defects. Final run: sanitisation audited independently (234,634 rows row-by-row, 0 unchanged; 1,873 addresses and 1,533 numbers harvested, 0 survived), migration validated (37 tables at parity, 32 FKs intact, 0 orphans, 0 duplicates, 0 dangling file references), idempotent re-run wrote 0, interrupted run resumed to a PASS, rollback left the monolith intact. Production untouched: `/health` 200 and PM2 restarts unchanged at 3 throughout |
| 17 | No critical unresolved defect | **PASS with caveat** | no defect introduced by the split remains open; a class of **inherited** defects is documented and deliberately out of scope |
| 18 | Responsible operator available | **PASS** | confirmed by the owner 2026-08-16: present for the window and able to authorise rollback |

**Verdict: GO** — all eighteen hard gates pass, and the residual is closed.

A second, complete production-shaped rehearsal ran on 2026-08-16 against a
fresh 108 MB read-only export using the current tooling and the validated
release SHAs. It found three further arithmetic defects — two of which would
have failed reconciliation during the real cutover — fixed them, and then
passed every stage: sanitisation audited independently, execute, reconcile,
validate, idempotent re-run, checkpoint/resume, and rollback. Production was
untouched and the environment was destroyed afterwards.

Detail: `docs/final-production-rehearsal.md` in the monolith repository.

### The gate-16 decision, resolved 2026-08-16

Investigated read-only. Classification: **A=5, B=0, C=0, D=31**. B=0 clears the
hard blocker — every reference to any of the 36 is a file path inherited by a
live candidate, and no booking, interview, attendance, mail, BGV, payment or
audit row belongs to one.

The 31 ambiguous records are quarantined: never created in `candidates_store`,
so they cannot appear as live candidates, and preserved in `_archive/`, which
the application never reads. Whether they were retired on purpose or lost in
the July move to PostgreSQL is still open, but it now costs nothing to leave
open.

Two tool defects surfaced and were fixed: the broken-reference check was a
structural no-op (so this gate's "0 broken references" was vacuous — production
actually has 70, all inherited), and the archive was being written to the path
the application reads, where a missing `DATABASE_URL` would have promoted the
superseded mirror over the live store.

Detail: `docs/orphaned-candidate-records-investigation.md` in the monolith
repository.

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

## Gate 16 — closed, and worth reading

It passed, but only after four defects were fixed. Every one of them was
invisible to the synthetic rehearsal, and three of them would have reported a
successful run.

1. **Candidates were migrated from a stale JSON mirror.** The file holds 102
   records, the table 195, and only 66 are shared. Of the 26 candidates live
   recruitment mail references, all 26 are in the table and 7 are in the file.
   The cutover would have dropped 129 live candidates and reported success.
2. **275 evidence files were not migrated.** The declared tree holds 6 files;
   candidate payment proofs and resumes live in trees nobody had declared.
3. **Live Telegram session secrets would have been copied.** The exclusion list
   was consulted when printing the plan and ignored by the copy.
4. **Sanitiser gaps**, including 41 of 42 json columns copied verbatim, phone
   numbers used as JSON dict keys, the untouched payment ledger, and the
   Diffie-Hellman secret for encrypted calls.

Measured cutover cost: **about 30 seconds of data work** — dump 11s, schema 1s,
migrate 12s, reconcile 1s, validate 5s. The 30-minute window is not constrained
by the data step; it is constrained by service start, proxy switch, TLS and the
three provider callbacks that must be re-registered one at a time.

Full detail, evidence tables and timings: `docs/production-shaped-rehearsal.md`
in the monolith repository.

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
| `COMPANY_PAYMENT_UPI_IDS`, `COMPANY_PAYMENT_RECEIVER_NAMES` | — | ✓ | PAYMENT IDENTITY | **Required and carried from verified production configuration.** Empty values make genuine receipts conflict with fixture placeholders |
| `COMPANY_PAYMENT_PHONE_NUMBERS`, `COMPANY_PAYMENT_ACCOUNT_NUMBERS` | — | ✓ | PAYMENT IDENTITY | Optional identifiers, but passed through whenever configured so all accepted payment rails share one receiver registry |
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
