#!/usr/bin/env bash
# Bring up isolated staging on a host that already runs something on 80/443.
#
# Run ON the staging host, from the Marketing repository root, with both
# repositories extracted side by side at their exact release commits.
#
#   STAGING_IP=<public-ipv4> bash scripts/staging_deploy_cotenant.sh
#
# The stack binds loopback-only high ports; the host's existing nginx fronts it
# with new server blocks for two staging hostnames. Production server blocks are
# never edited, and nginx is reloaded gracefully rather than restarted, so the
# production workload is not interrupted.
set -euo pipefail

: "${STAGING_IP:?set STAGING_IP to the public IPv4 of this host}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PEER="$(cd "$HERE/../teleautomation-business" && pwd)"
ENV_FILE="$HERE/.env.staging"
COMPOSE="docker compose -f docker-compose.staging.yml -f docker-compose.cotenant.yml"

MKT_HOST="marketing.${STAGING_IP}.sslip.io"
OPS_HOST="operations.${STAGING_IP}.sslip.io"

# Releases are shipped as git archives of an exact commit, which carry no .git
# directory, so the commit is supplied explicitly. Falling back to rev-parse
# keeps this usable in a normal clone.
MKT_SHA="${RELEASE_SHA_MARKETING:-$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)}"
OPS_SHA="${RELEASE_SHA_OPERATIONS:-$(git -C "$PEER" rev-parse HEAD 2>/dev/null || echo unknown)}"
[ "$MKT_SHA" = unknown ] && { echo "set RELEASE_SHA_MARKETING"; exit 1; }
[ "$OPS_SHA" = unknown ] && { echo "set RELEASE_SHA_OPERATIONS"; exit 1; }

echo "== releases under deployment =="
echo "  marketing  $MKT_SHA"
echo "  operations $OPS_SHA"

if [ ! -f "$ENV_FILE" ]; then
  echo "== generating staging-only secrets =="
  gen() { openssl rand -hex 24; }
  cat > "$ENV_FILE" <<EOF
# Generated $(date -u +%Y-%m-%dT%H:%M:%SZ). Staging only. Never commit.
STAGING_IP=$STAGING_IP
RELEASE_SHA_MARKETING=$MKT_SHA
RELEASE_SHA_OPERATIONS=$OPS_SHA
RELEASE_BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
MARKETING_DB_PASSWORD=$(gen)
OPERATIONS_DB_PASSWORD=$(gen)
INTERNAL_SERVICE_TOKEN=$(gen)
MARKETING_DASHBOARD_USERNAME=admin
MARKETING_DASHBOARD_PASSWORD=$(gen)
MARKETING_AUTH_SECRET=$(gen)
OPERATIONS_DASHBOARD_USERNAME=admin
OPERATIONS_DASHBOARD_PASSWORD=$(gen)
OPERATIONS_AUTH_SECRET=$(gen)
EOF
  chmod 600 "$ENV_FILE"
  echo "  wrote $ENV_FILE (0600)"
else
  echo "== reusing $ENV_FILE =="
  sed -i "s|^RELEASE_SHA_MARKETING=.*|RELEASE_SHA_MARKETING=$MKT_SHA|" "$ENV_FILE"
  sed -i "s|^RELEASE_SHA_OPERATIONS=.*|RELEASE_SHA_OPERATIONS=$OPS_SHA|" "$ENV_FILE"
fi

echo "== starting the staging stack (loopback ports only) =="
cd "$HERE"
$COMPOSE --env-file "$ENV_FILE" up -d --build

echo "== waiting for both services =="
for svc in marketing-api operations-api; do
  tries=90
  until [ "$(docker inspect -f '{{.State.Health.Status}}' \
        "$($COMPOSE --env-file "$ENV_FILE" ps -q $svc)" 2>/dev/null)" = "healthy" ]; do
    tries=$((tries-1)); [ $tries -le 0 ] && { echo "  $svc never became healthy"; exit 1; }
    sleep 2
  done
  echo "  $svc healthy"
done

echo "== installing staging nginx server blocks =="
# A NEW file for NEW hostnames. Production's site file is not touched.
sed "s/__STAGING_IP__/${STAGING_IP}/g" deploy/staging/nginx-staging.conf.template \
  > /etc/nginx/sites-available/teleautomation-staging
ln -sf /etc/nginx/sites-available/teleautomation-staging \
       /etc/nginx/sites-enabled/teleautomation-staging

if ! nginx -t 2>&1 | tail -2; then
  echo "  nginx config invalid; removing the staging site and leaving production untouched"
  rm -f /etc/nginx/sites-enabled/teleautomation-staging
  exit 1
fi
# Graceful reload: existing connections are served to completion. Not a restart.
systemctl reload nginx
echo "  nginx reloaded gracefully"

echo "== verifying production is still healthy =="
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 https://teleautomation.online/health)
[ "$code" = "200" ] || { echo "  PRODUCTION UNHEALTHY ($code) - rolling back the staging nginx site"; \
  rm -f /etc/nginx/sites-enabled/teleautomation-staging; systemctl reload nginx; exit 1; }
echo "  production /health still 200"

echo "== obtaining TLS certificates for the staging hostnames =="
# HTTP-01 through the nginx that already owns port 80. --nginx edits only the
# staging server blocks, because only those carry these server_names.
certbot --nginx --non-interactive --agree-tos --register-unsafely-without-email \
  --keep-until-expiring -d "$MKT_HOST" -d "$OPS_HOST" 2>&1 | tail -6

nginx -t >/dev/null 2>&1 && systemctl reload nginx
echo
echo "Marketing   https://$MKT_HOST"
echo "Operations  https://$OPS_HOST"
