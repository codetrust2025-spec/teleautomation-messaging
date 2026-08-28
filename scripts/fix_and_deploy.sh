#!/usr/bin/env bash
# Take an Operations change from branch to verified live production, resumably.
#
#   OPERATIONS_BRANCH=fix/thing KVM1_SSH=user@host bash scripts/fix_and_deploy.sh
#   OPERATIONS_SHA=<40-hex>     KVM1_SSH=user@host bash scripts/fix_and_deploy.sh
#
# Give a branch and it runs the whole pipeline. Give a commit already on
# Operations main and the first three stages find nothing to do and fall
# through to the deploy half.
#
#   ops_pr     open the Operations PR (description built from its commits)
#   ops_ci     poll its checks to completion
#   ops_merge  merge it, and record the resulting commit
#   preflight  confirm that commit is on Operations main; tools present
#   pin        branch, move the release anchor + contract test, push, open PR
#   pin_ci     poll the pin PR's checks
#   pin_merge  merge the pin PR
#   sync       on the host: no concurrent deploy, check out both repos, and
#              verify the anchor equals the Operations HEAD
#   build      build the operations-api image at that commit
#   deploy     recreate the container
#   verify     /version matches, health ok, all containers healthy, public 200
#
# Every stage is idempotent and records itself, so re-running after any
# interruption resumes at the first incomplete stage. Nothing here creates a
# second PR, merge, build or deployment for work already done: each mutating
# stage first asks the remote whether its effect is already present.
#
# Environment, because this repository holds no environment specifics (see the
# README: hostnames are supplied per deployment):
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

STAGES=(ops_pr ops_ci ops_merge preflight pin pin_ci pin_merge sync build deploy verify)

HERE="$(cd "$(dirname "$0")/.." && pwd)"
OPS_REPO="${OPS_REPO:-$(cd "$HERE/../teleautomation-business" 2>/dev/null && pwd || true)}"
COMPOSE_FILE="docker-compose.production.yml"
CONTRACT_TEST="tests/test_production_compose_contract.py"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-teleautomation-production}"
PROD_ENV_FILE="${PROD_ENV_FILE:-/etc/teleautomation-production.env}"
SERVICE="operations-api"
HEALTH_URL="http://127.0.0.1:8210"
PUBLIC_URL="https://operations.teleautomation.online/"

OPERATIONS_BRANCH="${OPERATIONS_BRANCH:-}"
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
  echo "fix_and_deploy — plan only, nothing will be changed"
  echo
  echo "  operations branch: ${OPERATIONS_BRANCH:-<unset>}"
  echo "  operations sha   : ${OPERATIONS_SHA:-<resolved by ops_merge>}"
  echo "  marketing repo   : $HERE"
  echo "  operations repo  : ${OPS_REPO:-<not found>}"
  echo "  ssh target       : ${KVM1_SSH:-<unset>}"
  echo "  compose project  : $COMPOSE_PROJECT"
  echo
  echo "  stages:"
  for s in "${STAGES[@]}"; do echo "    - $s"; done
  echo
  echo "  resumable: completed stages are recorded per run and skipped on re-run,"
  echo "  so restarting never opens a second PR or repeats a merge or deployment"
  exit 0
fi

# Arguments are validated before anything about the environment is inspected,
# so a malformed request says so plainly instead of failing later on a missing
# checkout and reporting the wrong problem.
[ -n "$OPERATIONS_BRANCH" ] || [ -n "$OPERATIONS_SHA" ] \
  || die "set OPERATIONS_BRANCH to the branch to ship, or OPERATIONS_SHA for a commit already on main"
if [ -n "$OPERATIONS_SHA" ]; then
  [ "${#OPERATIONS_SHA}" -eq 40 ] || die "OPERATIONS_SHA must be a full 40-character hex commit"
  case "$OPERATIONS_SHA" in
    *[!0-9a-f]*) die "OPERATIONS_SHA must be a full 40-character hex commit" ;;
  esac
fi

: "${KVM1_SSH:?set KVM1_SSH to user@host for the production host}"
[ -n "$OPS_REPO" ] || die "Operations repo not found; check it out beside this one or set OPS_REPO"
command -v gh >/dev/null || die "gh CLI is required"

KEY="$(printf '%s' "${OPERATIONS_BRANCH:-$OPERATIONS_SHA}" | tr -c 'A-Za-z0-9._-' '-')"
STATE_DIR="$HERE/.deploy-state"
STATE="$STATE_DIR/$KEY.stages"
SHA_FILE="$STATE_DIR/$KEY.sha"
mkdir -p "$STATE_DIR"
if [ "$RESTART" = "1" ]; then rm -f "$STATE" "$SHA_FILE"; fi
touch "$STATE"
# A resumed run picks the commit back up rather than re-deriving it, so the
# deploy half cannot drift onto a different commit than the one that was merged.
[ -z "$OPERATIONS_SHA" ] && [ -s "$SHA_FILE" ] && OPERATIONS_SHA="$(cat "$SHA_FILE")"

done_already() { grep -qx "$1" "$STATE"; }
mark_done() { echo "$1" >> "$STATE"; }

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15)
[ -n "${KVM1_SSH_KEY:-}" ] && SSH+=(-i "$KVM1_SSH_KEY")
SSH+=("$KVM1_SSH")

ops_gh() { gh --repo "$(git -C "$OPS_REPO" remote get-url origin | sed 's#.*[:/]\([^/]*/[^/]*\)\.git#\1#')" "$@"; }

branch_is_merged() {
  [ -n "$OPERATIONS_BRANCH" ] || return 0
  git -C "$OPS_REPO" fetch --quiet origin main
  git -C "$OPS_REPO" merge-base --is-ancestor "origin/$OPERATIONS_BRANCH" origin/main 2>/dev/null
}

# ── ops_pr ──────────────────────────────────────────────────────────────────
run_ops_pr() {
  if [ -z "$OPERATIONS_BRANCH" ]; then
    say "no branch given — starting from a commit already on main"
    return 0
  fi
  git -C "$OPS_REPO" fetch --quiet origin
  if branch_is_merged; then
    say "$OPERATIONS_BRANCH is already merged into main"
    return 0
  fi
  if ops_gh pr view "$OPERATIONS_BRANCH" --json number >/dev/null 2>&1; then
    say "PR for $OPERATIONS_BRANCH already open — reusing it"
    return 0
  fi
  # Description from the branch's own commits: they are written to explain the
  # change, so a generated body should quote them rather than invent a summary.
  local title body
  title="$(git -C "$OPS_REPO" log --format=%s "origin/main..origin/$OPERATIONS_BRANCH" | tail -1)"
  [ -n "$title" ] || die "$OPERATIONS_BRANCH has no commits ahead of main"
  body="$(git -C "$OPS_REPO" log --format='### %s%n%n%b' "origin/main..origin/$OPERATIONS_BRANCH")"
  ops_gh pr create --base main --head "$OPERATIONS_BRANCH" \
    --title "$title" \
    --body "$body

---
Opened by \`scripts/fix_and_deploy.sh\`. Body assembled from the commits on this branch." >/dev/null
  say "opened Operations PR for $OPERATIONS_BRANCH"
}

# ── ops_ci ──────────────────────────────────────────────────────────────────
run_ops_ci() {
  if [ -z "$OPERATIONS_BRANCH" ] || branch_is_merged; then
    say "nothing to poll"
    return 0
  fi
  say "polling Operations checks"
  ops_gh pr checks "$OPERATIONS_BRANCH" --watch --interval 20 >/dev/null \
    || die "Operations CI did not pass — read the run before retrying"
  say "Operations CI green"
}

# ── ops_merge ───────────────────────────────────────────────────────────────
run_ops_merge() {
  if [ -n "$OPERATIONS_BRANCH" ] && ! branch_is_merged; then
    local state
    state="$(ops_gh pr view "$OPERATIONS_BRANCH" --json mergeStateStatus -q .mergeStateStatus 2>/dev/null || echo UNKNOWN)"
    # A conflicted branch needs a human: resolving it means choosing which side
    # of the change survives, which is not a decision to automate.
    [ "$state" = "DIRTY" ] && die "$OPERATIONS_BRANCH has a merge conflict — resolve it, then re-run"
    ops_gh pr merge "$OPERATIONS_BRANCH" --merge --delete-branch >/dev/null \
      || die "could not merge the Operations PR"
    say "merged $OPERATIONS_BRANCH"
  fi
  if [ -z "$OPERATIONS_SHA" ]; then
    OPERATIONS_SHA="$(ops_gh pr view "$OPERATIONS_BRANCH" --json mergeCommit -q .mergeCommit.oid 2>/dev/null || true)"
    [ -n "$OPERATIONS_SHA" ] || die "could not determine the merge commit for $OPERATIONS_BRANCH"
    printf '%s' "$OPERATIONS_SHA" > "$SHA_FILE"
  fi
  say "Operations commit is ${OPERATIONS_SHA:0:7}"
}

# ── preflight ───────────────────────────────────────────────────────────────
run_preflight() {
  [ -n "$OPERATIONS_SHA" ] || die "no Operations commit resolved"
  git -C "$OPS_REPO" fetch --quiet origin main
  git -C "$OPS_REPO" merge-base --is-ancestor "$OPERATIONS_SHA" origin/main 2>/dev/null \
    || die "${OPERATIONS_SHA:0:7} is not on Operations origin/main"
  say "${OPERATIONS_SHA:0:7} is on Operations origin/main"
  "${SSH[@]}" true || die "cannot reach $KVM1_SSH over SSH"
  say "ssh to $KVM1_SSH ok"
}

# ── pin ─────────────────────────────────────────────────────────────────────
current_anchor() {
  git -C "$HERE" show origin/main:"$COMPOSE_FILE" \
    | sed -n 's/.*operations: &operations-release \([0-9a-f]\{40\}\).*/\1/p' | head -1
}
pin_branch() { echo "chore/pin-${OPERATIONS_SHA:0:7}"; }

run_pin() {
  git -C "$HERE" fetch --quiet origin main
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then
    say "anchor on main is already ${OPERATIONS_SHA:0:7}"
    return 0
  fi
  if gh pr view "$(pin_branch)" --json number >/dev/null 2>&1; then
    say "pin PR already open — reusing it"
    return 0
  fi
  local old; old="$(current_anchor)"
  [ -n "$old" ] || die "could not read the current release anchor from $COMPOSE_FILE"
  git -C "$HERE" checkout --quiet -B "$(pin_branch)" origin/main
  # Anchor and contract test move together, so a build can never be pinned to a
  # commit the test still expects to be the previous one.
  sed -i "s/$old/$OPERATIONS_SHA/g" "$HERE/$COMPOSE_FILE" "$HERE/$CONTRACT_TEST"
  git -C "$HERE" add "$COMPOSE_FILE" "$CONTRACT_TEST"
  git -C "$HERE" commit --quiet -m "pin Operations to ${OPERATIONS_SHA:0:7}" \
    -m "Moves the production release anchor ${old:0:7} -> ${OPERATIONS_SHA:0:7}."
  git -C "$HERE" push --quiet -u origin "$(pin_branch)"
  gh pr create --base main --head "$(pin_branch)" \
    --title "pin Operations to ${OPERATIONS_SHA:0:7}" \
    --body "Moves the production release anchor to \`${OPERATIONS_SHA:0:7}\`. Anchor and contract test move in the same commit." >/dev/null
  say "opened pin PR"
}

run_pin_ci() {
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then say "already pinned"; return 0; fi
  say "polling pin checks (dual-service is the slow one)"
  gh pr checks "$(pin_branch)" --watch --interval 20 >/dev/null \
    || die "pin CI did not pass — read the run before retrying"
  say "pin CI green"
}

run_pin_merge() {
  git -C "$HERE" fetch --quiet origin main
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then say "anchor already on main"; return 0; fi
  gh pr merge "$(pin_branch)" --merge --delete-branch >/dev/null || die "could not merge the pin PR"
  git -C "$HERE" fetch --quiet origin main
  [ "$(current_anchor)" = "$OPERATIONS_SHA" ] \
    || die "anchor on main is still not ${OPERATIONS_SHA:0:7} after merge"
  say "pin merged"
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
# The compose file requires the source checkout to be verified at this exact
# commit before any build. Building a tree that is not what the anchor claims
# would ship something no PR ever described.
[ "$ANCHOR" = "$HEAD" ] || { echo "  anchor $ANCHOR != head $HEAD" >&2; exit 1; }
echo "  checkouts synced; anchor matches head"
REMOTE
}

run_build() {
  "${SSH[@]}" "cd /opt/teleautomation/marketing && docker compose -p '$COMPOSE_PROJECT' \
    --env-file '$PROD_ENV_FILE' -f '$COMPOSE_FILE' build '$SERVICE'" >/dev/null || die "build failed"
  say "image built"
}

run_deploy() {
  "${SSH[@]}" "cd /opt/teleautomation/marketing && docker compose -p '$COMPOSE_PROJECT' \
    --env-file '$PROD_ENV_FILE' -f '$COMPOSE_FILE' up -d --no-deps '$SERVICE'" >/dev/null || die "deploy failed"
  say "container recreated"
}

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
echo "fix_and_deploy ${OPERATIONS_BRANCH:-${OPERATIONS_SHA:0:7}} -> production"
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
echo "DONE — ${OPERATIONS_SHA:0:7} is live and verified."
echo "Live behaviour still needs checking in the browser: a green deploy proves"
echo "the release is running, not that the change does what was asked."
