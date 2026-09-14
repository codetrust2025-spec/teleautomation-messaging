#!/usr/bin/env bash
# The cross-repository verification, shared by both pipelines.
#
# Run from anywhere, with this Marketing checkout beside an Operations checkout
# named teleautomation-business (the build contexts in docker-compose.dual.yml
# and docker-compose.staging.yml expect exactly that layout).
#
#   Marketing CI runs it when Marketing changes, against Operations main.
#   Operations CI runs it when Operations changes, against Marketing main.
#
# One script, so the two repositories cannot drift into verifying different
# things. It is the same sequence the Marketing `dual-service` job ran inline:
#
#   1. dual-service contracts         scripts/dual_service_test.sh
#   2. the staging stack over HTTP    scripts/staging_stack_check.sh
#   3. backup, restore and rollback   scripts/staging_{backup,restore,rollback}.sh
#
# Nothing here reads the production anchor, a production host or a production
# environment file. Every credential below is a throwaway value for containers
# that exist only for the length of the run.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

[ -d ../teleautomation-business ] || {
  echo "Operations must be checked out beside Marketing as ../teleautomation-business" >&2
  exit 1
}

# The commit under test, captured before the rollback rehearsal moves HEAD.
UNDER_TEST="$(git rev-parse HEAD)"

staging_env() {
  export STAGING_IP=127.0.0.1
  export MARKETING_SITE=http://marketing.test
  export OPERATIONS_SITE=http://operations.test
  export MARKETING_DB_PASSWORD=ci-marketing-db
  export OPERATIONS_DB_PASSWORD=ci-operations-db
  export INTERNAL_SERVICE_TOKEN=ci-internal-token
  export MARKETING_DASHBOARD_PASSWORD=ci-marketing-dash
  export MARKETING_AUTH_SECRET=ci-marketing-secret
  export OPERATIONS_DASHBOARD_PASSWORD=ci-operations-dash
  export OPERATIONS_AUTH_SECRET=ci-operations-secret
}

teardown() {
  status=$?
  git checkout --quiet "$UNDER_TEST" 2>/dev/null || true
  docker compose -f docker-compose.dual.yml down -v >/dev/null 2>&1 || true
  ( staging_env; docker compose -f docker-compose.staging.yml --profile edge down -v >/dev/null 2>&1 ) || true
  exit "$status"
}
trap teardown EXIT

echo "== 1. dual-service verification =="
# INTERNAL_SERVICE_TOKEN must not leak in from the staging values: the dual
# stack uses its own default, and the test asserts against that default.
( unset INTERNAL_SERVICE_TOKEN; bash scripts/dual_service_test.sh )
docker compose -f docker-compose.dual.yml down -v

echo
echo "== 2. staging stack over plain HTTP =="
# The staging stack adds TLS termination and two public hostnames on top of the
# dual-service stack. Automatic certificates need a public IP that CI does not
# have, but the compose wiring, the migrations, the release SHA baked into each
# image, the reverse proxy and the WebSocket upgrade are all testable here.
staging_env
export RELEASE_SHA_MARKETING="$UNDER_TEST"
# staging_stack_check.sh expects this exact literal for the Operations build.
export RELEASE_SHA_OPERATIONS=peer-under-test
# --profile edge starts Caddy. Without it Caddy is skipped and every proxy
# assertion in the check tests nothing.
docker compose -f docker-compose.staging.yml --profile edge up -d --build
bash scripts/staging_stack_check.sh

echo
echo "== 3. backup, restore and rollback =="
bash scripts/staging_backup.sh backups/ci
bash scripts/staging_restore.sh backups/ci

# Roll Marketing back one commit while Operations stays put. Beyond proving
# rollback works, this proves the two services are independently deployable:
# reverting one must not require touching the other.
PREV="$(git rev-parse "$UNDER_TEST~1")"
MARKETING_SHA="$PREV" bash scripts/staging_rollback.sh

# Return to the release under test so the stack is left as found.
git checkout --quiet "$UNDER_TEST"
RELEASE_SHA_MARKETING="$UNDER_TEST" \
  docker compose -f docker-compose.staging.yml up -d --build marketing-api

echo
echo "cross-repository verification passed at Marketing ${UNDER_TEST:0:7}"
