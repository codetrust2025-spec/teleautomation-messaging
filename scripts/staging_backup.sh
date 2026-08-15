#!/usr/bin/env bash
# Back up both staging services: databases, persistent data, and a checksum
# manifest.
#
#   bash scripts/staging_backup.sh [destination-directory]
#
# Each service is backed up independently, because they are independently
# deployable and must be independently restorable. A backup that can only be
# restored as a matched pair would couple two systems the split deliberately
# separated.
#
# Checksums are recorded per artefact so a restore can prove it read back what
# was written, rather than assuming it.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.staging.yml"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${1:-backups/$STAMP}"
mkdir -p "$DEST"

echo "== backing up to $DEST =="

dump_db() {
  local svc="$1" user="$2" db="$3"
  # Custom format: compressed, and restorable selectively by pg_restore.
  $COMPOSE exec -T "$svc" pg_dump -U "$user" -d "$db" --format=custom --no-owner --no-acl \
    > "$DEST/${db}.dump"
  echo "  ${db}.dump  $(wc -c < "$DEST/${db}.dump") bytes"
}

archive_volume() {
  local svc="$1" path="$2" name="$3"
  # Read the volume through the service container so no host path is assumed.
  $COMPOSE exec -T "$svc" tar -cf - -C "$path" . > "$DEST/${name}.tar" 2>/dev/null || true
  echo "  ${name}.tar  $(wc -c < "$DEST/${name}.tar") bytes"
}

echo "-- databases --"
dump_db marketing-db marketing marketing
dump_db operations-db operations operations

echo "-- persistent data --"
archive_volume marketing-api /var/lib/teleautomation-marketing marketing_data
archive_volume operations-api /var/lib/teleautomation-operations operations_data

echo "-- row counts at backup time --"
count_rows() {
  local svc="$1" table="$2"
  $COMPOSE exec -T "$svc" python -c "
import os,psycopg2
c=psycopg2.connect(os.environ['DATABASE_URL']);cur=c.cursor()
cur.execute('SELECT count(*) FROM \"$table\"');print(cur.fetchone()[0])" 2>/dev/null | tr -d '[:space:]'
}
{
  echo "marketing_schema_migrations=$(count_rows marketing-api marketing_schema_migrations)"
  echo "operations_schema_migrations=$(count_rows operations-api operations_schema_migrations)"
  echo "candidates_store=$(count_rows operations-api candidates_store)"
} > "$DEST/rowcounts.txt"
cat "$DEST/rowcounts.txt" | sed 's/^/  /'

echo "-- release identity --"
for pair in "marketing-api:marketing" "operations-api:operations"; do
  svc="${pair%%:*}"; name="${pair##*:}"
  $COMPOSE exec -T "$svc" python -c "
import urllib.request,json
print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/version',timeout=5))))" \
    > "$DEST/${name}_version.json" 2>/dev/null || echo '{}' > "$DEST/${name}_version.json"
  echo "  $name: $(cat "$DEST/${name}_version.json")"
done

echo "-- checksums --"
( cd "$DEST" && sha256sum ./*.dump ./*.tar ./rowcounts.txt ./*_version.json > SHA256SUMS )
sed 's/^/  /' "$DEST/SHA256SUMS"

echo
echo "backup complete: $DEST"
