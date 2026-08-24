# Marketing deployment runbook

Preparation only; do not execute against production without authorization.

- Linux user: `telemsg`
- release root: `/srv/teleautomation-messaging`
- environment: `/etc/teleautomation-messaging.env` (mode `0600`)
- writable data and Telegram sessions: `/var/lib/teleautomation-marketing`
- logs: `/var/log/teleautomation-messaging`
- bind: `127.0.0.1:8100`
- database/user: create dedicated Marketing names during staging provisioning

Build the image and frontend artifact in CI, then deploy only the versioned image. Run one API process initially because the account clients, workers, schedulers, and locks are process-local. Mount the Marketing data volume only into this service and set `TELEGRAM_SESSION_DIR=/var/lib/teleautomation-marketing`. Existing names are preserved: account N uses `/var/lib/teleautomation-marketing/session_accountN.session` (including SQLite sidecars). Never mount Operations storage.

Create a dedicated database/user with a generated password supplied through `psql` variables; revoke public access, grant the application user only its database/schema, and prove that it cannot connect to the Operations database. Set `DATABASE_URL`, `MARKETING_DATA_DIR`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, distinct dashboard credentials/secrets, provider settings, both Operations URLs, and the cross-service token through the protected environment file.

Preflight: verify disk/RAM, existing services, ports, Nginx, certificates, timers/cron, database sizes, media sizes, and session checksums. Validate `GET /health`, API contracts, `/ws`, account isolation, and a non-sending Telegram session check before enabling workers.

Backup with `pg_dump --format=custom`, a checksum manifest of the writable data/session tree, and protected copies of the environment and Nginx/service definitions. Verify by restoring to an isolated database and comparing object/row counts and file checksums. Roll back by stopping new queue intake, retaining post-cutover deltas, restoring the prior image and proxy config, then reconciling queued work. This procedure is not verified until exercised on staging.
