# Production cutover runbook

Status: **PREPARED — NOT EXECUTED.** Nothing in this document may be run against
production without the explicit authorisation `APPROVE PRODUCTION CUTOVER`.

Target architecture:

| Hostname | Serves |
|---|---|
| `teleautomation.online` | static entry page only — never an application |
| `marketing.teleautomation.online` | Marketing service, independently released |
| `operations.teleautomation.online` | Operations service, independently released |

The monolith keeps running on its own port and its own database throughout, and
is not stopped until the split has been stable for an agreed period. It is the
rollback target, so destroying it early destroys the rollback.

---

## 1. Release identity

Fix these before starting. Everything below refers to them.

| | Commit |
|---|---|
| Marketing | PR #11 merge commit; record the exact SHA before deployment |
| Operations | `d72633702ede6da5556b42e61155cfe21aca6b67` |
| Monolith rollback target | `68a28ecf2301c537eb8ee96f7d30649bd832c2f1` |

Both services report their commit at `/version`. Every verification step below
checks it, because a service quietly running an older image makes every other
signal meaningless. The unified production Compose pins the Operations build
argument to the approved SHA; the Operations source checkout must match it.

---

## 2. DNS plan

Two new A records. The apex is **not** changed at this stage.

| Record | Type | Value | TTL |
|---|---|---|---|
| `marketing` | A | `187.127.169.159` | **300** while cutting over |
| `operations` | A | `187.127.169.159` | **300** while cutting over |
| `teleautomation.online` | A | unchanged | unchanged |

Lower both TTLs to 300 **at least 24 hours before** the window, so the old value
has expired everywhere by the time it matters. Raise to 3600 once stable.

Rollback: the subdomains are new, so DNS rollback means deleting them. Nothing
that currently resolves changes, which is what makes this step low-risk.

Verify before proceeding: `dig +short marketing.teleautomation.online` returns
the VPS IP from at least two resolvers.

---

## 3. TLS plan

Certificates are issued **before** any traffic is moved, using the nginx that
already owns port 80:

```bash
certbot --nginx -d marketing.teleautomation.online -d operations.teleautomation.online
```

- The existing `teleautomation.online` certificate is **not touched**. It has its
  own lifecycle and remains valid for the entry page.
- Renewal is already installed via certbot's systemd timer; new certificates
  join it automatically. Confirm with `certbot renew --dry-run`.
- Issuance requires the DNS records from §2 to resolve, so §2 precedes §3.

---

## 4. Reverse proxy

`deploy/production/nginx-production.conf.template` installs as its own file with
its own `server_name`s. The existing production site file is not edited.

1. Render the template, substituting the two loopback ports.
2. `nginx -t` — abort on any error.
3. `systemctl reload nginx` — graceful; in-flight requests complete. **Never
   `restart`.**
4. Re-check `https://teleautomation.online/health` is still 200.

The apex block switches from proxying the monolith to serving the static entry
page. **That is the single moment production behaviour changes**, and it is the
step to roll back first if anything is wrong.

WebSocket upgrade headers are set explicitly in every proxy block. nginx drops
them silently otherwise, and the failure only appears once a proxy is in front —
which is exactly this change.

---

## 5. Databases

`deploy/production/provision_databases.sh` creates two databases with dedicated
owners, revokes the default `PUBLIC` grants, and then **proves isolation**: each
user can reach its own database and is denied the other's and the monolith's.
The script exits non-zero if any of those proofs fail.

New databases are created **alongside** the monolith's. Nothing existing is
renamed, altered or dropped.

---

## 6. Data cutover

### Write sources that must be quiet first

A migration is only consistent if nothing is writing behind it. Before extract:

1. Stop the monolith's background workers and schedulers (PM2 `telegram-backend`
   is the process; stopping it stops the writers with it).
2. Confirm no queue consumer is mid-flight.
3. Confirm the Gmail poller is not in a cycle — ingestion is poll-based on a
   ~13.5 minute interval, so a poll can land during the window.

This is the **write freeze**, and it is the only period of user-visible
downtime. Everything before it is preparation; everything after it is
verification.

### Sequence

| # | Step | Reversible? |
|---|---|---|
| 1 | Fresh `pg_dump --format=custom` of the monolith database + checksum | n/a |
| 2 | Verify the dump restores into a scratch database | n/a |
| 3 | Snapshot `/opt/telegramforward` data, session and evidence trees + checksums | n/a |
| 4 | **Begin write freeze** — stop the monolith process | yes, restart it |
| 5 | `split_migrate.py --dry-run` against the frozen data; read the counts | yes |
| 6 | `split_migrate.py --execute --confirm-non-production` into the two new stores | yes — new stores only, source untouched |
| 7 | `split_migrate.py --reconcile` — must report PASS | yes |
| 8 | Validate every foreign key in both destinations | yes |
| 9 | Bring up the production compose stack | yes |
| 10 | Install nginx config, reload | **first irreversible-feeling step** — but reversible by restoring the previous file |
| 11 | Re-point provider callbacks (§7) | partially — some providers need manual re-registration |
| 12 | Verification (§8) | n/a |
| 13 | **End write freeze** — traffic served by the split | — |

The migration **reads** the monolith's data and **writes** to new stores. It
never mutates the source, so steps 5–8 can be repeated. The tool is idempotent
and checkpointed, so an interrupted run resumes rather than duplicating.

### Telegram sessions

57 session files currently live in `/opt/telegramforward`. These are **live
credentials**, and a Telegram session used from two processes at once can be
invalidated by the server.

They must be **moved, not copied**, and only after the monolith is stopped.
Marketing owns them. The migration tool deliberately refuses to copy `*.session`
files, so this step is manual, deliberate, and done exactly once.

### Maximum acceptable freeze window

The monolith database is **349 MB**. Dump, migrate and reconcile at that size is
minutes, not hours. Budget **30 minutes**, with a hard stop at 60: if
reconciliation has not passed by then, roll back rather than continue, because
every additional minute is user-visible downtime with an unverified result.

---

## 7. Provider callbacks

See `docs/production-provider-callbacks.md` for the derived inventory.

Principle: any URL a provider stores on **their** side must be re-registered, and
each is a separate manual step that can fail independently. Do them one at a
time, verifying each, rather than as a batch.

Nothing here may be changed before authorisation — re-pointing a live callback
is a production change.

---

## 8. Verification before declaring success

Every one of these must pass. Any failure stops the cutover and triggers §9.

| Check | Expected |
|---|---|
| `teleautomation.online` | entry page loads, links to both subdomains |
| `marketing…/health`, `operations…/health` | 200 |
| `/version` on both | exactly the SHAs in §1 |
| TLS | valid certificate on all three hostnames |
| Login on both | succeeds; cookie `Secure`, `HttpOnly`, `SameSite` |
| Cross-service contracts | both directions authenticated; anonymous refused |
| WSS | upgrade reaches the app on `/ws` and `/ws/mail-monitoring` |
| Reconciliation | row counts and foreign keys match the pre-migration snapshot |
| Outbox | drains; no dead-lettered events |
| `monitor.sh` | exits 0 |

---

## 9. Rollback

Rollback is fastest at the proxy, so try that first.

| Failure | Action | Recovery time |
|---|---|---|
| Anything before the write freeze | stop; nothing has changed | immediate |
| Split services unhealthy after deploy | restore the previous nginx site file, reload, restart the monolith process | ~2 minutes |
| Reconciliation fails | do not proceed; the monolith database is untouched, so restart the monolith and investigate offline | ~2 minutes |
| Data problem found after traffic moved | restore the nginx file, restart the monolith, **move the session files back** | ~5 minutes |
| Corruption in the monolith database | restore the §6 step-1 dump | ~15 minutes |

The monolith database is never written to by the migration, so in every case
above the rollback target is intact. The rollback that actually needs care is the
**session files**, because they moved.

Keep the monolith release, its database and its data tree for **at least 14 days**
after cutover. Do not reclaim that disk early.

---

## 10. Post-cutover

Monitor with `deploy/production/monitor.sh` every 5 minutes for the first 24
hours. Watch specifically:

- outbox depth on both services — the split's one runtime dependency
- authentication failures — a cookie-scope mistake shows up here first
- Gmail ingestion resuming its poll cycle
- payment and booking volumes against the previous week

Do not begin unrelated feature work until 48 hours have passed without a
production defect.
