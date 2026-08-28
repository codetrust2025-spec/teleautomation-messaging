#!/usr/bin/env bash
# Ship an Operations commit to live production, end to end, resumably.
#
#   OPERATIONS_SHA=<40-hex> KVM1_SSH=user@host bash scripts/fix_and_deploy.sh
#
# The stages below are the whole pipeline. Every one is idempotent and records
# itself, so re-running after any interruption resumes at the first stage that
# has not completed rather than repeating work or double-merging.
#
#   preflight  the commit really is on Operations origin/main; tools present
#   pin        branch, move the release anchor + contract test, push, open PR
#   pin_ci     poll the pin PR's checks to completion
#   pin_merge  merge the pin PR
#   sync       on the host: no concurrent deploy, fetch and check out both
#              repos, and verify the anchor equals the Operations HEAD
#   build      build the operations-api image at that commit
#   deploy     recreate the container
#   verify     /version matches, health ok, all containers healthy, public 200
#
# What this deliberately does NOT do: create or merge the Operations PR. That
# one carries the actual change and needs a human-authored description and
# review; everything downstream of it is mechanical, which is why it is here.
#
# Environment, because this repository holds no environment specifics (see the
# README: hostnames are supplied per deployment):
#
#   KVM1_SSH       required   user@host for the production host
#   KVM1_SSH_KEY   optional   identity file; omit to use your ssh config
#   PROD_ENV_FILE  optional   host path to the compose env file
#   COMPOSE_PROJECT optional  compose project name
#
# Flags:
#   --dry-run   print the plan and exit without touching anything
#   --restart   discard recorded progress and run every stage again

set -euo pipefail

STAGES=(preflight pin pin_ci pin_merge sync build deploy verify)

HERE="$(cd "$(dirname "$0")/.." && pwd)"
OPS_REPO="${OPS_REPO:-$(cd "$HERE/../teleautomation-business" 2>/dev/null && pwd || true)}"
COMPOSE_FILE="docker-compose.production.yml"
CONTRACT_TEST="tests/test_production_compose_contract.py"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-teleautomation-production}"
PROD_ENV_FILE="${PROD_ENV_FILE:-/etc/teleautomation-production.env}"
SERVICE="operations-api"
HEALTH_URL="http://127.0.0.1:8210"
PUBLIC_URL="https://operations.teleautomation.online/"

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
stage_banner() { printf '\n== %s ==\n' "$1"; }
die() { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }

if [ "$DRY_RUN" = "1" ]; then
  echo "fix_and_deploy — plan only, nothing will be changed"
  echo
  echo "  operations sha : ${OPERATIONS_SHA:-<unset>}"
  echo "  marketing repo : $HERE"
  echo "  operations repo: ${OPS_REPO:-<not found>}"
  echo "  ssh target     : ${KVM1_SSH:-<unset>}"
  echo "  compose project: $COMPOSE_PROJECT"
  echo
  echo "  stages:"
  for s in "${STAGES[@]}"; do echo "    - $s"; done
  echo
  echo "  resumable: completed stages are recorded per commit and skipped on re-run"
  exit 0
fi

: "${OPERATIONS_SHA:?set OPERATIONS_SHA to the 40-character Operations commit to deploy}"
: "${KVM1_SSH:?set KVM1_SSH to user@host for the production host}"
[ -n "$OPS_REPO" ] || die "Operations repo not found; check it out beside this one or set OPS_REPO"
case "$OPERATIONS_SHA" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
  *) die "OPERATIONS_SHA must be a full 40-character hex commit" ;;
esac
[ "${#OPERATIONS_SHA}" -eq 40 ] || die "OPERATIONS_SHA must be a full 40-character hex commit"

SHORT="${OPERATIONS_SHA:0:7}"
STATE_DIR="$HERE/.deploy-state"
STATE="$STATE_DIR/$OPERATIONS_SHA"
mkdir -p "$STATE_DIR"
[ "$RESTART" = "1" ] && rm -f "$STATE"
touch "$STATE"

done_already() { grep -qx "$1" "$STATE"; }
mark_done() { echo "$1" >> "$STATE"; }

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15)
[ -n "${KVM1_SSH_KEY:-}" ] && SSH+=(-i "$KVM1_SSH_KEY")
SSH+=("$KVM1_SSH")

PIN_BRANCH="chore/pin-$SHORT"

# ── preflight ───────────────────────────────────────────────────────────────
run_preflight() {
  command -v gh >/dev/null || die "gh CLI is required"
  git -C "$OPS_REPO" fetch --quiet origin main
  git -C "$OPS_REPO" merge-base --is-ancestor "$OPERATIONS_SHA" origin/main 2>/dev/null \
    || die "$SHORT is not on Operations origin/main — merge the Operations PR first"
  say "$SHORT is on Operations origin/main"
  "${SSH[@]}" true || die "cannot reach $KVM1_SSH over SSH"
  say "ssh to $KVM1_SSH ok"
}

# ── pin ─────────────────────────────────────────────────────────────────────
current_anchor() {
  git -C "$HERE" show origin/main:"$COMPOSE_FILE" \
    | sed -n 's/.*operations: &operations-release \([0-9a-f]\{40\}\).*/\1/p' | head -1
}

run_pin() {
  git -C "$HERE" fetch --quiet origin main
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then
    say "anchor on origin/main is already $SHORT — nothing to pin"
    return 0
  fi
  if gh pr view "$PIN_BRANCH" --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)" >/dev/null 2>&1; then
    say "pin PR for $SHORT already open"
    return 0
  fi
  local old; old="$(current_anchor)"
  [ -n "$old" ] || die "could not read the current release anchor from $COMPOSE_FILE"
  git -C "$HERE" checkout --quiet -B "$PIN_BRANCH" origin/main
  # Anchor and contract test move together, so a build can never be pinned to a
  # commit the test still expects to be the previous one.
  sed -i "s/$old/$OPERATIONS_SHA/g" "$HERE/$COMPOSE_FILE" "$HERE/$CONTRACT_TEST"
  git -C "$HERE" add "$COMPOSE_FILE" "$CONTRACT_TEST"
  git -C "$HERE" commit --quiet -m "pin Operations to $SHORT" \
    -m "Moves the production release anchor $(echo "$old" | cut -c1-7) -> $SHORT."
  git -C "$HERE" push --quiet -u origin "$PIN_BRANCH"
  gh pr create --base main --head "$PIN_BRANCH" \
    --title "pin Operations to $SHORT" \
    --body "Moves the production release anchor to \`$SHORT\`. Anchor and contract test move in the same commit." >/dev/null
  say "opened pin PR for $SHORT"
}

# ── pin_ci ──────────────────────────────────────────────────────────────────
run_pin_ci() {
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then
    say "already pinned on main — no CI to wait for"
    return 0
  fi
  say "polling checks (dual-service is the slow one)"
  gh pr checks "$PIN_BRANCH" --watch --interval 20 >/dev/null \
    || die "pin CI did not pass — read the run before retrying"
  say "pin CI green"
}

# ── pin_merge ───────────────────────────────────────────────────────────────
run_pin_merge() {
  git -C "$HERE" fetch --quiet origin main
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then
    say "anchor already on main"
    return 0
  fi
  gh pr merge "$PIN_BRANCH" --merge --delete-branch >/dev/null \
    || die "could not merge the pin PR"
  git -C "$HERE" fetch --quiet origin main
  [ "$(current_anchor)" = "$OPERATIONS_SHA" ] || die "anchor on main is still not $SHORT after merge"
  say "pin merged; anchor on main is $SHORT"
}

# ── sync ────────────────────────────────────────────────────────────────────
run_sync() {
  local marketing_sha
  marketing_sha="$(git -C "$HERE" rev-parse origin/main)"
  "${SSH[@]}" bash -s -- "$OPERATIONS_SHA" "$marketing_sha" <<'REMOTE' || die "sync failed"
set -euo pipefail
OPS_SHA="$1"; MKT_SHA="$2"
if ps aux | grep -E "docker (compose|build)" | grep -v grep >/dev/null; then
  echo "  another deploy is already running on this host — refusing" >&2
  exit 1
fi
cd /opt/teleautomation/teleautomation-business
git fetch --quiet origin main && git checkout --quiet "$OPS_SHA"
cd /opt/teleautomation/marketing
git fetch --quiet origin main && git checkout --quiet "$MKT_SHA"
ANCHOR=$(sed -n 's/.*operations: &operations-release \([0-9a-f]\{40\}\).*/\1/p' \
  /opt/teleautomation/marketing/docker-compose.production.yml | head -1)
HEAD=$(git -C /opt/teleautomation/teleautomation-business rev-parse HEAD)
# The compose file says the source checkout must be verified at this exact
# commit before any build. Building a tree that is not what the anchor claims
# would ship something no PR ever described.
[ "$ANCHOR" = "$HEAD" ] || { echo "  anchor $ANCHOR != head $HEAD" >&2; exit 1; }
echo "  checkouts synced; anchor matches head"
REMOTE
}

# ── build ───────────────────────────────────────────────────────────────────
run_build() {
  "${SSH[@]}" "cd /opt/teleautomation/marketing && docker compose -p '$COMPOSE_PROJECT' \
    --env-file '$PROD_ENV_FILE' -f '$COMPOSE_FILE' build '$SERVICE'" >/dev/null \
    || die "build failed"
  say "image built"
}

# ── deploy ──────────────────────────────────────────────────────────────────
run_deploy() {
  "${SSH[@]}" "cd /opt/teleautomation/marketing && docker compose -p '$COMPOSE_PROJECT' \
    --env-file '$PROD_ENV_FILE' -f '$COMPOSE_FILE' up -d --no-deps '$SERVICE'" >/dev/null \
    || die "deploy failed"
  say "container recreated"
}

# ── verify ──────────────────────────────────────────────────────────────────
run_verify() {
  "${SSH[@]}" bash -s -- "$OPERATIONS_SHA" "$COMPOSE_PROJECT" "$HEALTH_URL" "$PUBLIC_URL" <<'REMOTE' || die "verification failed"
set -euo pipefail
WANT="$1"; PROJECT="$2"; HEALTH="$3"; PUBLIC="$4"
for i in $(seq 1 30); do
  s=$(docker inspect "${PROJECT}-operations-api-1" --format '{{.State.Health.Status}}' 2>/dev/null || true)
  [ "$s" = "healthy" ] && break
  sleep 10
done
GOT=$(curl -s -m 10 "$HEALTH/version" | sed -n 's/.*"sha":"\([0-9a-f]*\)".*/\1/p')
[ "$GOT" = "$WANT" ] || { echo "  /version is $GOT, expected $WANT" >&2; exit 1; }
echo "  /version  $(echo "$GOT" | cut -c1-7)"
curl -s -m 10 "$HEALTH/health" | grep -q '"status":"ok"' || { echo "  health not ok" >&2; exit 1; }
echo "  health    ok"
TOTAL=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Status}}' | wc -l)
OK=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Status}}' | grep -c healthy)
[ "$OK" = "$TOTAL" ] || { echo "  only $OK/$TOTAL containers healthy" >&2; exit 1; }
echo "  containers $OK/$TOTAL healthy"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$PUBLIC")
[ "$CODE" = "200" ] || { echo "  public returned $CODE" >&2; exit 1; }
echo "  public    200"
REMOTE
}

# ── run ─────────────────────────────────────────────────────────────────────
echo "fix_and_deploy $SHORT -> production"
for stage in "${STAGES[@]}"; do
  if done_already "$stage"; then
    printf '\n== %s == (already done, skipping)\n' "$stage"
    continue
  fi
  stage_banner "$stage"
  "run_$stage"
  mark_done "$stage"
done

echo
echo "DONE — $SHORT is live and verified."
echo "Live behaviour still needs checking in the browser: a green deploy proves"
echo "the release is running, not that the change does what was asked."
