#!/usr/bin/env bash
# Production health probe for the split.
#
#   bash deploy/production/monitor.sh            # human output
#   bash deploy/production/monitor.sh --quiet    # only problems; exit 1 if any
#
# Intended for cron every few minutes. Read-only: it reports, it never restarts,
# scales or repairs anything. An automated remediation during a cutover window
# is how a small problem becomes an outage.
#
# Checks the things that actually page someone: is each service answering, is it
# serving the release we think it is, is either database unreachable, is
# cross-project delivery backing up, and is the disk about to fill.
set -uo pipefail

QUIET=0; [ "${1:-}" = "--quiet" ] && QUIET=1
PROBLEMS=0

ROOT_URL=${ROOT_URL:-https://teleautomation.online}
MKT_URL=${MKT_URL:-https://marketing.teleautomation.online}
OPS_URL=${OPS_URL:-https://operations.teleautomation.online}
COMPOSE=${COMPOSE:-docker compose -f /opt/teleautomation/docker-compose.production.yml --env-file /opt/teleautomation/.env.production}
DISK_WARN_PCT=${DISK_WARN_PCT:-85}
OUTBOX_WARN=${OUTBOX_WARN:-25}

say()  { [ "$QUIET" -eq 1 ] || printf '  %s\n' "$1"; }
warn() { printf '  PROBLEM  %s\n' "$1"; PROBLEMS=$((PROBLEMS+1)); }

http() { curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$1" 2>/dev/null; }

section() { [ "$QUIET" -eq 1 ] || printf '\n== %s ==\n' "$1"; }

section "reachability"
for pair in "root:$ROOT_URL/" "marketing:$MKT_URL/health" "operations:$OPS_URL/health"; do
  n="${pair%%:*}"; u="${pair#*:}"
  c=$(http "$u")
  [ "$c" = "200" ] && say "$n $c" || warn "$n returned ${c:-no response} ($u)"
done

section "release identity"
# A service silently running an older image than intended is the failure mode
# that makes every other signal misleading.
for pair in "marketing:$MKT_URL" "operations:$OPS_URL"; do
  n="${pair%%:*}"; u="${pair#*:}"
  sha=$(curl -sS --max-time 15 "$u/version" 2>/dev/null \
        | python3 -c 'import json,sys;print(json.load(sys.stdin).get("sha","?"))' 2>/dev/null)
  if [ -z "$sha" ] || [ "$sha" = "?" ] || [ "$sha" = "unknown" ]; then
    warn "$n does not report a release SHA"
  else
    say "$n serving $sha"
    exp_var="EXPECT_$(printf '%s' "$n" | tr '[:lower:]' '[:upper:]')_SHA"
    exp="${!exp_var:-}"
    [ -n "$exp" ] && [ "$sha" != "$exp" ] && warn "$n serving $sha, expected $exp"
  fi
done

section "databases"
for svc in marketing operations; do
  ok=$($COMPOSE exec -T "${svc}-api" python -c "
import os,psycopg2
try:
    psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=5).close(); print('ok')
except Exception as e: print('fail:'+type(e).__name__)" 2>/dev/null | tr -d '[:space:]')
  [ "$ok" = "ok" ] && say "$svc database reachable" || warn "$svc database: ${ok:-unreachable}"
done

section "cross-project delivery"
# A growing outbox means Marketing cannot reach Operations. It is the earliest
# signal that the split's one runtime dependency is failing, and it degrades
# quietly rather than throwing.
for svc in marketing operations; do
  read -r pending dead <<<"$($COMPOSE exec -T "${svc}-api" python -c "
from services import cross_project_outbox as o
rows=o._load()
print(sum(1 for r in rows if r.get('delivered_at') is None and r.get('status')!='dead'),
      sum(1 for r in rows if r.get('status')=='dead'))" 2>/dev/null)"
  pending=${pending:-?}; dead=${dead:-0}
  if [ "$pending" = "?" ]; then
    warn "$svc outbox unreadable"
  else
    [ "$pending" -gt "$OUTBOX_WARN" ] && warn "$svc outbox backing up: $pending pending" \
                                      || say "$svc outbox pending=$pending"
    [ "${dead:-0}" -gt 0 ] && warn "$svc outbox has $dead dead-lettered event(s)"
  fi
done

section "host"
use=$(df --output=pcent / | tail -1 | tr -dc '0-9')
[ "${use:-0}" -ge "$DISK_WARN_PCT" ] && warn "disk ${use}% used" || say "disk ${use}% used"
free -m | awk 'NR==2{ if ($7+0 < 512) print "  PROBLEM  memory available "$7"MB"; else print "  memory available "$7"MB" }'

section "containers"
down=$($COMPOSE ps --status exited --status dead -q 2>/dev/null | wc -l)
[ "${down:-0}" -gt 0 ] && warn "$down container(s) not running" || say "all containers running"

section "backups"
# A backup job that stopped running is invisible until it is needed.
LATEST=$(ls -1dt /var/backups/teleautomation-* 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  warn "no backup directory found"
else
  age_h=$(( ( $(date +%s) - $(stat -c %Y "$LATEST") ) / 3600 ))
  [ "$age_h" -gt 26 ] && warn "newest backup is ${age_h}h old ($LATEST)" \
                      || say "newest backup ${age_h}h old"
fi

[ "$QUIET" -eq 1 ] || printf '\n'
if [ "$PROBLEMS" -eq 0 ]; then
  [ "$QUIET" -eq 1 ] || echo "all checks passed"
  exit 0
fi
echo "$PROBLEMS problem(s)"
exit 1
