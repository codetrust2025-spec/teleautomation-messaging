#!/usr/bin/env bash
# Break-glass: build an Operations commit on the production host and release it.
#
# This is NOT how production is normally released. Merging to Operations main
# releases production through .github/workflows/deploy.yml in the Operations
# repository: CI builds the image once, pushes it to the private registry, and
# the host's teleautomation-deploy pulls it, verifies it and rolls back on
# failure. Use this only when that path cannot run -- GitHub Actions or the
# registry is unavailable -- and the release cannot wait for it.
#
#   OPERATIONS_SHA=<40-hex on Operations main> KVM1_SSH=user@host bash scripts/fix_and_deploy.sh
#
#   preflight  the commit is on Operations main; the host answers and already
#              records releases
#   sync       on the host: no deploy in flight; the Operations checkout at the
#              commit, Marketing main beside it
#   build      build operations-api on the host from that exact checkout,
#              stamped with the commit, and tag it release-<sha>
#   release    teleautomation-deploy deploy-local <sha>: the same label check,
#              restart, verification and automatic rollback a CI release gets
#
# Stages record themselves, so an interrupted run resumes. If production already
# serves the commit from its recorded release, build and release both skip.
#
# Environment -- this repository holds no environment specifics:
#
#   KVM1_SSH        required  user@host for the production host
#   KVM1_SSH_KEY    optional  identity file; omit to use your ssh config
#   PROD_ENV_FILE   optional  host path to the compose env file
#   COMPOSE_PROJECT optional  compose project name
#
# Flags:
#   --dry-run   print the plan and exit without touching anything
#   --restart   discard recorded progress and run every stage again

set -euo pipefail

STAGES=(preflight sync build release)

HERE="$(cd "$(dirname "$0")/.." && pwd)"
OPS_REPO="${OPS_REPO:-$(cd "$HERE/../teleautomation-business" 2>/dev/null && pwd || true)}"
COMPOSE_FILE="docker-compose.production.yml"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-teleautomation-production}"
PROD_ENV_FILE="${PROD_ENV_FILE:-/etc/teleautomation-production.env}"
SERVICE="operations-api"
LOCAL_IMAGE="teleautomation-production-operations-api"
HEALTH_URL="http://127.0.0.1:8210"
DEPLOY_SCRIPT="/usr/local/sbin/teleautomation-deploy"
RELEASE_FILE="/etc/teleautomation/operations-release.env"

OPERATIONS_SHA="${OPERATIONS_SHA:-}"

DRY_RUN=0
RESTART=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --restart) RESTART=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }
die() { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }

if [ "$DRY_RUN" = "1" ]; then
  echo "fix_and_deploy (break-glass) — plan only, nothing will be changed"
  echo
  echo "  normal releases: merge to Operations main; this is for when CI cannot release"
  echo
  echo "  operations sha   : ${OPERATIONS_SHA:-<unset>}"
  echo "  marketing repo   : $HERE"
  echo "  operations repo  : ${OPS_REPO:-<not found>}"
  echo "  ssh target       : ${KVM1_SSH:-<unset>}"
  echo "  compose project  : $COMPOSE_PROJECT"
  echo
  echo "  stages:"
  for s in "${STAGES[@]}"; do echo "    - $s"; done
  echo
  echo "  resumable: completed stages are recorded per run and skipped on re-run,"
  echo "  and build and release skip when production already serves the commit"
  exit 0
fi

# Arguments are validated before anything about the environment is inspected,
# so a malformed request says so plainly instead of failing later on a missing
# checkout and reporting the wrong problem.
if [ -z "$OPERATIONS_SHA" ]; then
  die "set OPERATIONS_SHA to a full 40-character commit already on Operations main. Normal releases do not use this script: merge to Operations main and its deploy workflow releases production"
fi
[ "${#OPERATIONS_SHA}" -eq 40 ] || die "OPERATIONS_SHA must be a full 40-character hex commit"
case "$OPERATIONS_SHA" in
  *[!0-9a-f]*) die "OPERATIONS_SHA must be a full 40-character hex commit" ;;
esac

: "${KVM1_SSH:?set KVM1_SSH to user@host for the production host}"
[ -n "$OPS_REPO" ] || die "Operations repo not found; check it out beside this one or set OPS_REPO"

STATE_DIR="$HERE/.deploy-state"
STATE="$STATE_DIR/break-glass-$OPERATIONS_SHA.stages"
mkdir -p "$STATE_DIR"
if [ "$RESTART" = "1" ]; then rm -f "$STATE"; fi
touch "$STATE"

done_already() { grep -qx "$1" "$STATE"; }
mark_done() { echo "$1" >> "$STATE"; }

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15)
[ -n "${KVM1_SSH_KEY:-}" ] && SSH+=(-i "$KVM1_SSH_KEY")
SSH+=("$KVM1_SSH")

# ── preflight ───────────────────────────────────────────────────────────────
run_preflight() {
  git -C "$OPS_REPO" fetch --quiet origin main
  git -C "$OPS_REPO" merge-base --is-ancestor "$OPERATIONS_SHA" origin/main 2>/dev/null \
    || die "${OPERATIONS_SHA:0:7} is not on Operations origin/main"
  say "${OPERATIONS_SHA:0:7} is on Operations origin/main"
  "${SSH[@]}" true || die "cannot reach $KVM1_SSH over SSH"
  # Releasing needs somewhere to record the release and a previous one to roll
  # back to. A host that has never been set up has neither.
  "${SSH[@]}" "test -x $DEPLOY_SCRIPT && test -f $RELEASE_FILE" \
    || die "the host does not record releases yet; run scripts/setup_ci_deploy.sh first"
  say "the host records releases"
}

# ── sync ────────────────────────────────────────────────────────────────────
run_sync() {
  local marketing_sha
  git -C "$HERE" fetch --quiet origin main
  marketing_sha="$(git -C "$HERE" rev-parse origin/main)"
  "${SSH[@]}" bash -s -- "$OPERATIONS_SHA" "$marketing_sha" <<'REMOTE' || die "sync failed"
set -euo pipefail
OPS_SHA="$1"; MKT_SHA="$2"
PROCS=$(ps -eo args || true)
if grep -E '^docker (compose|build)' <<<"$PROCS" | grep -v grep >/dev/null; then
  echo "  another deploy is already running on this host — refusing" >&2
  exit 1
fi
cd /opt/teleautomation/teleautomation-business
git fetch --quiet origin main && git checkout --quiet "$OPS_SHA"
cd /opt/teleautomation/marketing
git fetch --quiet origin main && git checkout --quiet "$MKT_SHA"
HEAD=$(git -C /opt/teleautomation/teleautomation-business rev-parse HEAD)
# The image is stamped with the commit it is built from. Building any other tree
# would stamp a commit the image does not contain.
[ "$HEAD" = "$OPS_SHA" ] || { echo "  checkout is $HEAD, expected $OPS_SHA" >&2; exit 1; }
echo "  checkouts synced at ${OPS_SHA:0:7}"
REMOTE
}

# Is production already serving this commit from its recorded release? Asked of
# the host, so the skip survives losing the local stage record.
already_live() {
  "${SSH[@]}" bash -s -- "$OPERATIONS_SHA" "$HEALTH_URL" "$RELEASE_FILE" <<'REMOTE' >/dev/null 2>&1
set -euo pipefail
WANT="$1"; HEALTH="$2"; RELEASE="$3"
GOT=$(curl -s -m 10 "$HEALTH/version" | sed -n 's/.*"sha":"\([0-9a-f]*\)".*/\1/p')
RECORDED=$(sed -n 's/^OPERATIONS_RELEASE_SHA=//p' "$RELEASE")
[ "$GOT" = "$WANT" ] && [ "$RECORDED" = "$WANT" ]
REMOTE
}

# ── build ───────────────────────────────────────────────────────────────────
run_build() {
  if already_live; then
    say "production already serves ${OPERATIONS_SHA:0:7} from its recorded release — nothing to build"
    return 0
  fi
  "${SSH[@]}" bash -s -- "$OPERATIONS_SHA" "$COMPOSE_PROJECT" "$PROD_ENV_FILE" "$COMPOSE_FILE" "$SERVICE" "$LOCAL_IMAGE" <<'REMOTE' || die "build failed"
set -euo pipefail
SHA="$1"; PROJECT="$2"; ENV_FILE="$3"; COMPOSE="$4"; SERVICE="$5"; IMAGE="$6"
cd /opt/teleautomation/marketing
# Deliberately without the release file: this builds the service's own image
# name, stamped with OPERATIONS_BUILD_SHA, and never names a registry image.
OPERATIONS_BUILD_SHA="$SHA" docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE" build "$SERVICE" >/dev/null
docker tag "$IMAGE" "$IMAGE:release-$SHA"
echo "  built and tagged $IMAGE:release-${SHA:0:7}"
REMOTE
}

# ── release ─────────────────────────────────────────────────────────────────
run_release() {
  if already_live; then
    say "production already serves ${OPERATIONS_SHA:0:7} — nothing to release"
    return 0
  fi
  # The same checks, restart, verification and automatic rollback as a CI
  # release; on failure it has already restored and verified the previous one.
  "${SSH[@]}" "$DEPLOY_SCRIPT deploy-local $OPERATIONS_SHA" \
    || die "the release did not verify; teleautomation-deploy reported what it restored above"
}

# ── run ─────────────────────────────────────────────────────────────────────
echo "fix_and_deploy (break-glass) ${OPERATIONS_SHA:0:7} -> production"
for stage in "${STAGES[@]}"; do
  if done_already "$stage"; then
    printf '\n== %s == (already done, skipping)\n' "$stage"
    continue
  fi
  printf '\n== %s ==\n' "$stage"
  "run_$stage"
  mark_done "$stage"
done

echo
echo "DONE — ${OPERATIONS_SHA:0:7} is live and verified, released outside CI."
echo "The next merge to Operations main releases normally. Live behaviour still"
echo "needs checking in the browser: a verified release is not a verified change."
