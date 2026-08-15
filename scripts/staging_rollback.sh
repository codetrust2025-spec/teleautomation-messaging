#!/usr/bin/env bash
# Roll the staging deployment back to a previous release and verify it.
#
#   MARKETING_SHA=<prev> OPERATIONS_SHA=<prev> bash scripts/staging_rollback.sh
#
# Rollback rebuilds the application containers at the previous commits and
# leaves the databases and volumes in place, because that is what a real
# rollback does: the data stays, the code moves back. It therefore also proves
# the previous release still works against the current schema, which is the
# property that actually matters and the one that silently breaks after a
# forward-only migration.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.staging.yml"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PEER="$(cd "$HERE/../teleautomation-business" && pwd)"

# Either service may be rolled back alone. That is the point of the split: a
# Marketing regression must be revertible without touching Operations, and vice
# versa. Leave a SHA unset to hold that service at its current release.
: "${MARKETING_SHA:=}"
: "${OPERATIONS_SHA:=}"
[ -n "$MARKETING_SHA$OPERATIONS_SHA" ] || {
  echo "set MARKETING_SHA and/or OPERATIONS_SHA to the release being rolled back to"; exit 1; }

REBUILD=""
echo "== rolling back to =="
if [ -n "$MARKETING_SHA" ]; then
  echo "  marketing  $MARKETING_SHA"
  git -C "$HERE" checkout --quiet "$MARKETING_SHA"
  export RELEASE_SHA_MARKETING="$MARKETING_SHA"
  REBUILD="$REBUILD marketing-api"
else
  echo "  marketing  unchanged"
fi
if [ -n "$OPERATIONS_SHA" ]; then
  echo "  operations $OPERATIONS_SHA"
  git -C "$PEER" checkout --quiet "$OPERATIONS_SHA"
  export RELEASE_SHA_OPERATIONS="$OPERATIONS_SHA"
  REBUILD="$REBUILD operations-api"
else
  echo "  operations unchanged"
fi

# Only the application containers are rebuilt. Databases and volumes are
# untouched, so persistent state carries across the rollback.
# shellcheck disable=SC2086
$COMPOSE up -d --build $REBUILD

echo "== verifying the rolled-back release =="
FAIL=0
wait_healthy() {
  local svc="$1" tries=90
  while [ $tries -gt 0 ]; do
    local cid; cid=$($COMPOSE ps -q "$svc" 2>/dev/null)
    if [ -n "$cid" ]; then
      local st; st=$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null)
      [ "$st" = "healthy" ] && return 0
    fi
    sleep 2; tries=$((tries-1))
  done
  return 1
}

for pair in "marketing-api:$MARKETING_SHA" "operations-api:$OPERATIONS_SHA"; do
  svc="${pair%%:*}"; want="${pair#*:}"
  [ -n "$want" ] || continue
  if wait_healthy "$svc"; then
    echo "  PASS  $svc healthy after rollback"
  else
    echo "  FAIL  $svc did not become healthy after rollback"; FAIL=$((FAIL+1)); continue
  fi
  got=$($COMPOSE exec -T "$svc" python -c "
import urllib.request,json
print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/version',timeout=5))['sha'])" 2>&1 | tr -d '[:space:]')
  if [ "$got" = "$want" ]; then
    echo "  PASS  $svc reports the rolled-back commit"
  else
    echo "  FAIL  $svc reports ${got:-none}, expected $want"; FAIL=$((FAIL+1))
  fi
done

echo "== previous release still works against the current schema =="
for pair in "marketing-api:marketing_schema_migrations" "operations-api:operations_schema_migrations"; do
  svc="${pair%%:*}"; table="${pair#*:}"
  n=$($COMPOSE exec -T "$svc" python -c "
import os,psycopg2
c=psycopg2.connect(os.environ['DATABASE_URL']);cur=c.cursor()
cur.execute('SELECT count(*) FROM \"$table\"');print(cur.fetchone()[0])" 2>/dev/null | tr -d '[:space:]')
  if [ "${n:-0}" -ge 1 ]; then
    echo "  PASS  $svc reads its database after rollback ($n migrations)"
  else
    echo "  FAIL  $svc cannot read its database after rollback"; FAIL=$((FAIL+1))
  fi
done

echo
[ "$FAIL" -eq 0 ] && echo "rollback verified" || echo "rollback FAILED with $FAIL problem(s)"
exit "$FAIL"
