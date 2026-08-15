#!/usr/bin/env bash
# Validate the staging stack without a public IP.
#
# Automatic certificates need a publicly reachable host, so TLS itself cannot be
# exercised here. Everything else that breaks on a first deployment can be:
# compose wiring, migrations, the release SHA baked into the image, the reverse
# proxy, and the WebSocket upgrade. Caddy routes on the Host header, so the same
# Caddyfile is exercised over plain HTTP by sending the staging hostnames.
set -uo pipefail

COMPOSE="docker compose -f docker-compose.staging.yml"
PASS=0; FAIL=0
ok()  { printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  FAIL  %s -- %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }
step(){ printf '\n== %s ==\n' "$1"; }

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

step "1-2. Application containers become healthy"
wait_healthy marketing-api && ok "Marketing healthy" || bad "Marketing healthy"
wait_healthy operations-api && ok "Operations healthy" || bad "Operations healthy"

step "3-4. Migrations ran against the staging databases"
for pair in "marketing:2" "operations:30"; do
  svc="${pair%%:*}"; min="${pair##*:}"
  n=$($COMPOSE exec -T "${svc}-api" python -c "
import os,psycopg2
c=psycopg2.connect(os.environ['DATABASE_URL']);cur=c.cursor()
cur.execute(\"select count(*) from information_schema.tables where table_schema='public'\")
print(cur.fetchone()[0])" 2>/dev/null | tr -d '[:space:]')
  [ "${n:-0}" -ge "$min" ] && ok "${svc} schema present ($n tables)" || bad "${svc} schema" "tables=${n:-none}"
done

step "5. Databases are genuinely separate"
# Operations tables must not exist in the Marketing database.
leak=$($COMPOSE exec -T marketing-api python -c "
import os,psycopg2
c=psycopg2.connect(os.environ['DATABASE_URL']);cur=c.cursor()
cur.execute(\"select to_regclass('candidates_store') is not null\")
print(cur.fetchone()[0])" 2>/dev/null | tr -d '[:space:]')
[ "$leak" = "False" ] && ok "Marketing database has no Operations tables" \
  || bad "Database separation" "candidates_store present in Marketing: $leak"

step "6-7. Each service reports the commit it is running"
want_mkt="${RELEASE_SHA_MARKETING:-unknown}"
got=$($COMPOSE exec -T marketing-api python -c "
import urllib.request,json
print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/version',timeout=5))['sha'])" 2>/dev/null | tr -d '[:space:]')
[ "$got" = "$want_mkt" ] && ok "Marketing /version reports $got" || bad "Marketing /version" "want=$want_mkt got=${got:-none}"
got=$($COMPOSE exec -T operations-api python -c "
import urllib.request,json
d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/version',timeout=5))
print(d['sha'], d['service'])" 2>/dev/null)
case "$got" in
  *peer-under-test*teleautomation-operations*) ok "Operations /version reports its build ($got)";;
  *) bad "Operations /version" "got=${got:-none}";;
esac

step "8-9. Caddy routes each hostname to the right service"
code=$(curl -sS -o /dev/null -w '%{http_code}' -H 'Host: marketing.test' --max-time 20 http://127.0.0.1/health)
[ "$code" = "200" ] && ok "marketing.test -> Marketing (200)" || bad "Caddy routes marketing.test" "got $code"
svc=$(curl -sS -H 'Host: operations.test' --max-time 20 http://127.0.0.1/health | tr -d '[:space:]')
case "$svc" in *teleautomation-operations*) ok "operations.test -> Operations ($svc)";;
               *) bad "Caddy routes operations.test" "got ${svc:-none}";; esac

step "10. Caddy does not cross-route the two hostnames"
mkt_ver=$(curl -sS -H 'Host: marketing.test' --max-time 20 http://127.0.0.1/version | tr -d '[:space:]')
case "$mkt_ver" in *teleautomation-messaging*) ok "marketing.test is not served by Operations";;
                   *) bad "Hostname isolation" "marketing.test returned $mkt_ver";; esac

step "11-12. Caddy passes the WebSocket upgrade through"
# A 101 means proxy upgraded and app accepted; 401/403 means proxy upgraded and
# the app refused an anonymous client. Both prove the proxy forwards the upgrade.
# 400/426/502 mean the proxy is swallowing it, which is the failure that only
# ever appears once something sits in front of the app.
for pair in "marketing.test:/ws" "operations.test:/ws/mail-monitoring"; do
  host="${pair%%:*}"; path="${pair#*:}"
  line=$(curl -sS -i --max-time 20 -o - \
        -H "Host: $host" -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
        -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
        "http://127.0.0.1$path" 2>/dev/null | head -1 | tr -d '\r')
  case "$line" in
    *101*|*401*|*403*) ok "WebSocket upgrade reached the app on $host$path ($line)";;
    *) bad "WebSocket upgrade $host$path" "proxy did not forward: ${line:-no response}";;
  esac
done

step "13. Internal endpoints refuse anonymous callers through the proxy"
code=$(curl -sS -o /dev/null -w '%{http_code}' -H 'Host: operations.test' --max-time 20 \
      -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1/internal/v1/opportunities)
case "$code" in 401|403) ok "Operations internal endpoint refuses anonymous ($code)";;
                *) bad "Internal endpoint exposure" "got $code";; esac

step "14. No secret is echoed in service logs"
if $COMPOSE logs marketing-api operations-api caddy 2>/dev/null \
   | grep -qE 'ci-internal-token|ci-marketing-dash|ci-operations-dash|ci-marketing-secret|ci-operations-secret'; then
  bad "Secrets absent from logs" "a staging secret was printed"
else
  ok "Secrets absent from logs"
fi

printf '\n===== staging stack check: %d passed, %d failed =====\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
