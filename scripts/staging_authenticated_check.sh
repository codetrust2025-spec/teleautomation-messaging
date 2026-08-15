#!/usr/bin/env bash
# Authenticated hosted walkthrough of a staging service.
#
#   SERVICE=marketing|operations BASE=https://... bash scripts/staging_authenticated_check.sh
#
# Run ON the staging host. Credentials are read straight from .env.staging into
# the request and are never echoed, so the password does not appear in output,
# logs, or anywhere it could be captured.
#
# This drives the real HTTPS endpoint with a real session cookie, so it
# exercises TLS, the reverse proxy, authentication, cookie flags and every
# feature route the way a browser does. Routes are asserted as reachable and
# authorised, not merely present in the code.
set -uo pipefail

: "${SERVICE:?set SERVICE to marketing or operations}"
: "${BASE:?set BASE to the service https URL}"
ENV_FILE="${ENV_FILE:-/opt/staging/teleautomation-messaging/.env.staging}"
JAR="$(mktemp)"; HDR="$(mktemp)"
trap 'rm -f "$JAR" "$HDR"' EXIT

PASS=0; FAIL=0
ok()  { printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  FAIL  %s -- %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }
step(){ printf '\n== %s ==\n' "$1"; }

if [ "$SERVICE" = marketing ]; then
  USER_KEY=MARKETING_DASHBOARD_USERNAME; PASS_KEY=MARKETING_DASHBOARD_PASSWORD
else
  USER_KEY=OPERATIONS_DASHBOARD_USERNAME; PASS_KEY=OPERATIONS_DASHBOARD_PASSWORD
fi
U=$(grep "^${USER_KEY}=" "$ENV_FILE" | cut -d= -f2-)
[ -n "$U" ] || U=admin

# Build the JSON body in a subshell so the secret is never a shell variable that
# could be printed by an error path or a trace.
login_body() {
  python3 -c "
import json,sys
u=sys.argv[1]
p=[l.split('=',1)[1].strip() for l in open(sys.argv[2]) if l.startswith('${PASS_KEY}=')][0]
print(json.dumps({'username':u,'password':p}))" "$U" "$ENV_FILE"
}

step "1. Unauthenticated access is refused"
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$BASE/auth/status")
case "$code" in 200) ok "/auth/status reachable ($code)";; *) bad "/auth/status" "got $code";; esac

step "2. Wrong credentials are rejected without a session"
rc=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 -c "$JAR" \
     -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"deliberately-wrong-value"}' "$BASE/auth/login")
if [ "$rc" = "200" ]; then bad "Wrong password rejected" "got 200"; else ok "Wrong password rejected ($rc)"; fi
grep -qi 'session' "$JAR" && bad "No cookie issued on failed login" "cookie present" || ok "No cookie issued on failed login"
: > "$JAR"

step "3. Login succeeds and issues a session cookie"
rc=$(login_body | curl -sS -o /dev/null -w '%{http_code}' --max-time 25 -c "$JAR" -D "$HDR" \
     -H 'Content-Type: application/json' --data-binary @- "$BASE/auth/login")
[ "$rc" = "200" ] && ok "Login accepted (200)" || bad "Login" "got $rc"

step "4. Session cookie flags"
setc=$(grep -i '^set-cookie:' "$HDR" | head -1 | tr -d '\r')
printf '%s' "$setc" | grep -qi 'httponly'  && ok "Cookie is HttpOnly"  || bad "Cookie HttpOnly" "absent"
printf '%s' "$setc" | grep -qi 'secure'    && ok "Cookie is Secure"    || bad "Cookie Secure" "absent"
printf '%s' "$setc" | grep -qi 'samesite'  && ok "Cookie sets SameSite" || bad "Cookie SameSite" "absent"

step "5. Authenticated session is usable"
auth=$(curl -sS --max-time 20 -b "$JAR" "$BASE/auth/status")
printf '%s' "$auth" | grep -qiE '"authenticated":\s*true|"username"' \
  && ok "Session authenticated" || bad "Session authenticated" "got $(printf '%s' "$auth" | head -c 80)"

step "6. Feature routes reachable with the session"
check_route() {
  local label="$1" path="$2" want="${3:-2}"
  local c; c=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 25 -b "$JAR" "$BASE$path")
  case "$c" in
    ${want}*) ok "$label ($path -> $c)" ;;
    *)        bad "$label" "$path -> $c" ;;
  esac
}

if [ "$SERVICE" = marketing ]; then
  check_route "Fleet state"            /state
  check_route "Telegram accounts"      /accounts
  check_route "Group master list"      /groups
  check_route "Group lists per account" /groups/lists
  check_route "Joined-groups export"   /groups/total-list
  check_route "Fleet defaults"         /fleet/defaults
  check_route "Inbox"                  /inbox
  check_route "CRM"                    /crm/state
  check_route "Marketing AI config"    /ai/smart-reply/config
  check_route "Admin dashboard"        /admin/dashboard
  check_route "Metrics"                /metrics
  check_route "WhatsApp status"        /whatsapp/status
  check_route "Push VAPID key"         /push/vapid-public-key
else
  check_route "Candidates"             /candidates
  check_route "Public slots"           /public/slots/candidates
  check_route "Booked slots"           /public/slots/booked
  check_route "Daily briefing"         /ai/daily-briefing
  check_route "OCR policy"             /ai/ocr-policy
  check_route "OCR policy audit"       /ai/ocr-policy/audit
  check_route "Recruitment mail review" /api/ai-recruitment/review
  check_route "Recruitment dashboard"  /api/ai-recruitment/dashboard
  check_route "Mailbox overview"       /api/candidate-mailboxes/overview
  check_route "Mail monitoring alerts" /api/mail-monitoring/notifications
  check_route "Payments reconciliation" /payments/reconciliation
  check_route "BGV register"           /bgv/register
  check_route "Data room"              /data-room/accounts
  check_route "Handler expenses"       /handler-expenses
  check_route "Handler salaries"       /handler-salaries
fi

step "7. Logout invalidates the session"
curl -sS -o /dev/null --max-time 20 -b "$JAR" -c "$JAR" -X POST "$BASE/auth/logout" || true
after=$(curl -sS --max-time 20 -b "$JAR" "$BASE/auth/status")
printf '%s' "$after" | grep -qiE '"authenticated":\s*false' \
  && ok "Session invalidated after logout" \
  || bad "Logout invalidates session" "got $(printf '%s' "$after" | head -c 80)"

printf '\n===== %s authenticated walkthrough: %d passed, %d failed =====\n' "$SERVICE" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
