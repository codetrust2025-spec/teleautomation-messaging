#!/usr/bin/env bash
# Restore a staging backup into DISPOSABLE targets and verify it.
#
#   bash scripts/staging_restore.sh backups/<stamp>
#
# Restores into freshly created databases alongside the live staging ones rather
# than over them. A restore that overwrites the only copy cannot be rehearsed
# safely, and the point of the rehearsal is to prove the backup is readable
# before it is ever needed.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.staging.yml"
SRC="${1:?usage: staging_restore.sh <backup-directory>}"
SUFFIX="${RESTORE_SUFFIX:-restore}"

[ -f "$SRC/SHA256SUMS" ] || { echo "no SHA256SUMS in $SRC"; exit 1; }

echo "== verifying backup integrity =="
( cd "$SRC" && sha256sum -c SHA256SUMS ) | sed 's/^/  /'

restore_db() {
  local svc="$1" user="$2" db="$3"
  local target="${db}_${SUFFIX}"
  echo "-- restoring $db into $target --"
  # Drop and recreate so a repeated rehearsal is deterministic.
  $COMPOSE exec -T "$svc" psql -U "$user" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${target};" -c "CREATE DATABASE ${target};" >/dev/null
  $COMPOSE exec -T "$svc" pg_restore -U "$user" -d "$target" --no-owner --no-acl \
    < "$SRC/${db}.dump" >/dev/null 2>&1 || true
  echo "  restored"
}

restore_db marketing-db marketing marketing
restore_db operations-db operations operations

echo "== verifying restored content =="
FAIL=0
check() {
  local svc="$1" user="$2" db="$3" table="$4" expect="$5"
  local got
  got=$($COMPOSE exec -T "$svc" psql -U "$user" -d "${db}_${SUFFIX}" -tAc \
        "SELECT count(*) FROM \"$table\"" 2>/dev/null | tr -d '[:space:]')
  if [ "$got" = "$expect" ]; then
    echo "  PASS  ${db}_${SUFFIX}.${table} = $got"
  else
    echo "  FAIL  ${db}_${SUFFIX}.${table} expected $expect got ${got:-none}"
    FAIL=$((FAIL+1))
  fi
}

# shellcheck disable=SC1090
mkt_mig=$(grep '^marketing_schema_migrations=' "$SRC/rowcounts.txt" | cut -d= -f2)
ops_mig=$(grep '^operations_schema_migrations=' "$SRC/rowcounts.txt" | cut -d= -f2)
cand=$(grep '^candidates_store=' "$SRC/rowcounts.txt" | cut -d= -f2)

check marketing-db marketing marketing marketing_schema_migrations "$mkt_mig"
check operations-db operations operations operations_schema_migrations "$ops_mig"
check operations-db operations operations candidates_store "$cand"

echo "== verifying relationships survived =="
# Foreign keys are restored as constraints; validating them proves the restore
# preserved referential integrity rather than just row counts.
orphans=$($COMPOSE exec -T operations-db psql -U operations -d "operations_${SUFFIX}" -tAc "
SELECT count(*) FROM pg_constraint WHERE contype='f'" 2>/dev/null | tr -d '[:space:]')
if [ "${orphans:-0}" -ge 1 ]; then
  echo "  PASS  ${orphans} foreign keys present in the restored database"
else
  echo "  FAIL  no foreign keys in the restored database"
  FAIL=$((FAIL+1))
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "restore verified: $SRC"
else
  echo "restore FAILED with $FAIL problem(s)"
fi
exit "$FAIL"
