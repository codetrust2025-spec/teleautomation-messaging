#!/usr/bin/env bash
# Bring up isolated staging on a Docker host, at exact verified commits.
#
#   STAGING_IP=203.0.113.10 bash scripts/staging_deploy.sh
#
# Requires on the host: Docker, Compose v2, git, and ports 80/443 reachable from
# the internet so Let's Encrypt can validate over HTTP-01.
#
# Both repositories must be checked out side by side:
#   teleautomation-messaging/  teleautomation-business/
#
# Secrets are GENERATED here, staging-only, and written to a gitignored .env.
# No production secret is read or reused. Nothing generated here is committed.
set -euo pipefail

MARKETING_SHA="${MARKETING_SHA:-8a02f8af21a423c22886e52abe0e9bab4c127cb9}"
OPERATIONS_SHA="${OPERATIONS_SHA:-085ba525c8a64694ea636d5d264bd91ce7ab68c9}"
: "${STAGING_IP:?set STAGING_IP to the public IPv4 address of this host}"

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PEER="$(cd "$HERE/../teleautomation-business" && pwd)"
ENV_FILE="$HERE/.env.staging"

echo "== checking out the exact verified commits =="
# A staging deployment that is not an exact commit cannot be compared with the
# verification evidence, and cannot be rolled back to a known point.
git -C "$HERE" fetch --quiet origin
git -C "$HERE" checkout --quiet "$MARKETING_SHA"
git -C "$PEER" fetch --quiet origin
git -C "$PEER" checkout --quiet "$OPERATIONS_SHA"
echo "  marketing  $(git -C "$HERE" rev-parse --short HEAD)"
echo "  operations $(git -C "$PEER" rev-parse --short HEAD)"

if [ ! -f "$ENV_FILE" ]; then
  echo "== generating staging-only secrets =="
  gen() { openssl rand -hex 24; }
  cat > "$ENV_FILE" <<EOF
# Generated $(date -u +%Y-%m-%dT%H:%M:%SZ). Staging only. Never commit.
STAGING_IP=$STAGING_IP
ACME_EMAIL=${ACME_EMAIL:-}
RELEASE_SHA_MARKETING=$MARKETING_SHA
RELEASE_SHA_OPERATIONS=$OPERATIONS_SHA
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
  echo "  wrote $ENV_FILE (0600). Dashboard passwords are in it; read them there."
else
  echo "== reusing existing $ENV_FILE =="
  # Keep the recorded release in step with what is being deployed.
  sed -i "s|^RELEASE_SHA_MARKETING=.*|RELEASE_SHA_MARKETING=$MARKETING_SHA|" "$ENV_FILE"
  sed -i "s|^RELEASE_SHA_OPERATIONS=.*|RELEASE_SHA_OPERATIONS=$OPERATIONS_SHA|" "$ENV_FILE"
fi

cd "$HERE"
echo "== building and starting =="
docker compose --env-file "$ENV_FILE" -f docker-compose.staging.yml up -d --build

echo
echo "Marketing   https://marketing.$STAGING_IP.sslip.io"
echo "Operations  https://operations.$STAGING_IP.sslip.io"
echo
echo "Certificates take a few seconds on first start. Verify with:"
echo "  STAGING_IP=$STAGING_IP bash scripts/staging_verify.sh"
