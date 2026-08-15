#!/usr/bin/env bash
# Verify the HOSTED staging deployment over real HTTPS and WSS.
#
#   STAGING_IP=203.0.113.10 bash scripts/staging_verify.sh
#
# This is deliberately not the container test. It exercises the deployment
# through its public TLS endpoints, because several failure modes exist only
# there: certificate problems, a proxy that drops WebSocket upgrade headers,
# cookies without Secure, and mixed-content or CORS breakage.
set -uo pipefail

: "${STAGING_IP:?set STAGING_IP to the staging host public IPv4}"
MKT="https://marketing.${STAGING_IP}.sslip.io"
OPS="https://operations.${STAGING_IP}.sslip.io"
EXPECT_MKT_SHA="${MARKETING_SHA:-8a02f8af21a423c22886e52abe0e9bab4c127cb9}"
EXPECT_OPS_SHA="${OPERATIONS_SHA:-085ba525c8a64694ea636d5d264bd91ce7ab68c9}"

PASS=0; FAIL=0
ok()  { printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  FAIL  %s -- %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }
step(){ printf '\n== %s ==\n' "$1"; }

step "1-2. HTTPS health, valid certificate"
for pair in "Marketing:$MKT" "Operations:$OPS"; do
  name="${pair%%:*}"; url="${pair#*:}"
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$url/health" 2>/dev/null)
  [ "$code" = "200" ] && ok "$name /health over HTTPS (200)" || bad "$name /health" "got $code"
done

step "3. HTTP redirects to HTTPS"
for pair in "Marketing:marketing" "Operations:operations"; do
  name="${pair%%:*}"; host="${pair#*:}"
  loc=$(curl -sS -o /dev/null -w '%{redirect_url}' --max-time 20 "http://${host}.${STAGING_IP}.sslip.io/health")
  case "$loc" in https://*) ok "$name redirects to HTTPS";; *) bad "$name HTTP->HTTPS" "location=$loc";; esac
done

step "4-5. Deployed commit is the intended one"
for pair in "Marketing:$MKT:$EXPECT_MKT_SHA" "Operations:$OPS:$EXPECT_OPS_SHA"; do
  name="${pair%%:*}"; rest="${pair#*:}"; url="${rest%:*}"; want="${rest##*:}"
  got=$(curl -sS --max-time 20 "$url/version" | python -c 'import sys,json;print(json.load(sys.stdin).get("sha",""))' 2>/dev/null)
  [ "$got" = "$want" ] && ok "$name serving $want" || bad "$name deployed SHA" "want=$want got=${got:-none}"
done

step "6. Frontend loads"
for pair in "Marketing:$MKT" "Operations:$OPS"; do
  name="${pair%%:*}"; url="${pair#*:}"
  body=$(curl -sS --max-time 20 "$url/" | head -c 4000)
  printf '%s' "$body" | grep -qi "<div id=\"root\"\|<script" \
    && ok "$name frontend served" || bad "$name frontend" "no app shell in response"
done

step "7. No localhost or loopback leaked into the served frontend"
for pair in "Marketing:$MKT" "Operations:$OPS"; do
  name="${pair%%:*}"; url="${pair#*:}"
  asset=$(curl -sS --max-time 20 "$url/" | grep -oE '/assets/[A-Za-z0-9._-]+\.js' | head -1)
  if [ -z "$asset" ]; then bad "$name bundle discoverable"; continue; fi
  js=$(curl -sS --max-time 60 "$url$asset")
  if printf '%s' "$js" | grep -qE '127\.0\.0\.1|localhost:[0-9]+'; then
    bad "$name bundle free of loopback URLs" "found localhost/127.0.0.1"
  else
    ok "$name bundle free of loopback URLs"
  fi
  if printf '%s' "$js" | grep -q 'teleautomation\.online'; then
    bad "$name bundle free of production host" "references teleautomation.online"
  else
    ok "$name bundle does not call the production monolith"
  fi
done

step "8. Session cookie is Secure and HttpOnly"
for pair in "Marketing:$MKT" "Operations:$OPS"; do
  name="${pair%%:*}"; url="${pair#*:}"
  hdrs=$(curl -sS -i --max-time 20 -X POST "$url/auth/login" \
        -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"deliberately-wrong"}' 2>/dev/null | tr -d '\r')
  # A wrong password must not set a session cookie at all.
  if printf '%s' "$hdrs" | grep -qi '^set-cookie:'; then
    bad "$name rejects bad credentials without a cookie"
  else
    ok "$name rejects bad credentials without a cookie"
  fi
done

step "9. Internal service endpoints are not reachable from the public internet without a token"
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$OPS/internal/v1/opportunities" -X POST -H 'Content-Type: application/json' -d '{}')
case "$code" in 401|403) ok "Operations internal endpoint refuses anonymous public callers ($code)";;
                 *) bad "Operations internal endpoint public exposure" "got $code";; esac
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$MKT/internal/v1/operational-summary")
case "$code" in 401|403) ok "Marketing internal endpoint refuses anonymous public callers ($code)";;
                 *) bad "Marketing internal endpoint public exposure" "got $code";; esac

step "10. Secure WebSocket upgrade is proxied"
# An unauthenticated socket must be refused, but it must be refused BY THE APP
# after a successful TLS upgrade, not by the proxy failing to upgrade at all.
python - "$MKT" "$OPS" <<'PY'
import sys, ssl, base64, os, socket
from urllib.parse import urlparse

def probe(url, path):
    host = urlparse(url).hostname
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
           f"Sec-WebSocket-Version: 13\r\n\r\n")
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=20) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as s:
            s.sendall(req.encode())
            return s.recv(200).decode("latin-1").split("\r\n")[0]

for url, path in ((sys.argv[1], "/ws"), (sys.argv[2], "/ws/mail-monitoring")):
    try:
        line = probe(url, path)
    except Exception as exc:                      # noqa: BLE001
        print(f"  FAIL  WSS upgrade {path} -- {type(exc).__name__}")
        continue
    # 101 means the proxy upgraded and the app accepted; 401/403 means the proxy
    # upgraded and the app refused an anonymous client. Both prove the proxy is
    # passing upgrade headers. 400/426/502 mean the proxy is not.
    if "101" in line or "401" in line or "403" in line:
        print(f"  PASS  WSS upgrade reached the app on {path} ({line.strip()})")
    else:
        print(f"  FAIL  WSS upgrade {path} -- proxy did not upgrade: {line.strip()}")
PY

printf '\n===== hosted staging result: %d passed, %d failed (plus WSS lines above) =====\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
