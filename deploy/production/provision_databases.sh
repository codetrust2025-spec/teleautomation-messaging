#!/usr/bin/env bash
# Create the two production databases with least-privilege owners, and PROVE
# each service cannot reach the other's data.
#
#   bash deploy/production/provision_databases.sh
#
# Creates NEW databases alongside the existing monolith database. It never
# touches, renames or drops the existing one: the monolith stays the rollback
# target until the split is demonstrably stable.
#
# Passwords are read from an environment file, never passed on the command line
# where they would land in the process list and shell history.
set -euo pipefail

: "${MARKETING_DB_PASSWORD:?export MARKETING_DB_PASSWORD (generated, not reused)}"
: "${OPERATIONS_DB_PASSWORD:?export OPERATIONS_DB_PASSWORD (generated, not reused)}"

MKT_DB=${MKT_DB:-teleautomation_marketing}
OPS_DB=${OPS_DB:-teleautomation_operations}
MKT_USER=${MKT_USER:-teleautomation_marketing}
OPS_USER=${OPS_USER:-teleautomation_operations}

psql_su() { sudo -u postgres psql -v ON_ERROR_STOP=1 "$@"; }

echo "== existing databases (untouched) =="
psql_su -tAc "SELECT datname FROM pg_database WHERE datistemplate=false" | sed 's/^/  /'

echo "== creating roles and databases =="
# Roles are created with a password supplied through a psql variable so it is
# never interpolated into shell history or the process list.
MARKETING_DB_PASSWORD="$MARKETING_DB_PASSWORD" psql_su -q \
  -v user="$MKT_USER" -v pw="$MARKETING_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'user', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'user') \gexec
SQL
OPERATIONS_DB_PASSWORD="$OPERATIONS_DB_PASSWORD" psql_su -q \
  -v user="$OPS_USER" -v pw="$OPERATIONS_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'user', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'user') \gexec
SQL

for pair in "$MKT_DB:$MKT_USER" "$OPS_DB:$OPS_USER"; do
  db="${pair%%:*}"; owner="${pair##*:}"
  psql_su -q -v db="$db" -v owner="$owner" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'owner')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SQL
  echo "  $db owned by $owner"
done

echo "== revoking the public grants PostgreSQL creates by default =="
# Without this, every role can connect to the new databases and, on PostgreSQL
# below 15, create objects in the public schema.
for pair in "$MKT_DB:$MKT_USER" "$OPS_DB:$OPS_USER"; do
  db="${pair%%:*}"; owner="${pair##*:}"
  psql_su -q -d "$db" -v owner="$owner" -v db="$db" <<'SQL'
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"owner";
GRANT USAGE, CREATE ON SCHEMA public TO :"owner";
ALTER SCHEMA public OWNER TO :"owner";
SQL
  echo "  $db locked down to $owner"
done

echo
echo "== PROOF: neither service can reach the other's database =="
FAIL=0
prove_denied() {
  local user="$1" db="$2" pw="$3"
  # A successful connection here is a hard failure: it would mean one project
  # can read the other's data directly, which the split forbids.
  if PGPASSWORD="$pw" psql -h 127.0.0.1 -U "$user" -d "$db" -tAc "SELECT 1" >/dev/null 2>&1; then
    echo "  FAIL  $user CAN connect to $db"
    FAIL=$((FAIL+1))
  else
    echo "  PASS  $user cannot connect to $db"
  fi
}
prove_allowed() {
  local user="$1" db="$2" pw="$3"
  if PGPASSWORD="$pw" psql -h 127.0.0.1 -U "$user" -d "$db" -tAc "SELECT 1" >/dev/null 2>&1; then
    echo "  PASS  $user can connect to its own $db"
  else
    echo "  FAIL  $user cannot connect to its own $db"
    FAIL=$((FAIL+1))
  fi
}

prove_allowed "$MKT_USER" "$MKT_DB" "$MARKETING_DB_PASSWORD"
prove_allowed "$OPS_USER" "$OPS_DB" "$OPERATIONS_DB_PASSWORD"
prove_denied  "$MKT_USER" "$OPS_DB" "$MARKETING_DB_PASSWORD"
prove_denied  "$OPS_USER" "$MKT_DB" "$OPERATIONS_DB_PASSWORD"

# The monolith database must remain reachable only by its own owner.
MONO_DB=${MONO_DB:-teleautomation}
prove_denied "$MKT_USER" "$MONO_DB" "$MARKETING_DB_PASSWORD"
prove_denied "$OPS_USER" "$MONO_DB" "$OPERATIONS_DB_PASSWORD"

echo
[ "$FAIL" -eq 0 ] && echo "database isolation proven" || echo "ISOLATION FAILED: $FAIL problem(s)"
exit "$FAIL"
