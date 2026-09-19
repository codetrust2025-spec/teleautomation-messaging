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
#   ops_pr     open the Operations PR (description built from its commits) and
#              record its head: that commit is what ships
#   pin        branch, move the release anchor + contract test, push, open PR --
#              straight away, so both repositories' CI run at the same time
#   ops_ci     poll the Operations checks to completion
#   pin_ci     poll the pin PR's checks to completion
#   ops_merge  land the Operations PR by fast-forwarding main to exactly the
#              pinned commit; if main has moved, merge normally and re-pin
#   preflight  confirm that commit is on Operations main; tools present
#   pin_merge  merge the pin PR, refusing unless the pin is on Operations main
#   sync       on the host: no concurrent deploy, check out both repos, and
#              verify the anchor equals the Operations HEAD
#   build      build the operations-api image at that commit
#   deploy     recreate the container
#   verify     /version matches, health ok, all containers healthy, public 200
#
# Nothing merges until both CIs are green: a failure in either leaves both
# pull requests open and production untouched. The pin names the Operations
# PR's head and main is fast-forwarded to that same commit, so the commit CI
# tested, the commit Marketing pins and the commit on main are one commit.
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

STAGES=(ops_pr pin ops_ci pin_ci ops_merge preflight pin_merge sync build deploy verify)

HERE="$(cd "$(dirname "$0")/.." && pwd)"
OPS_REPO="${OPS_REPO:-$( { cd "$HERE/../teleautomation-business" 2>/dev/null \
  || cd "$HERE/../teleautomation-operations" 2>/dev/null; } && pwd || true)}"
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
  echo "  operations sha   : ${OPERATIONS_SHA:-<the PR head, recorded by ops_pr>}"
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
PIN_FILE="$STATE_DIR/$KEY.pin"
if [ "$RESTART" = "1" ]; then
  # A restart pins afresh, so the pin PR the discarded run opened must not
  # stay open beside the new one. It was never merged: closing it changes
  # nothing in production.
  if [ -s "$PIN_FILE" ] \
     && [ "$(gh pr view "$(cat "$PIN_FILE")" --json state -q .state 2>/dev/null)" = OPEN ]; then
    gh pr close "$(cat "$PIN_FILE")" --delete-branch \
      --comment "Superseded: fix_and_deploy.sh was restarted." >/dev/null || true
  fi
  rm -f "$STATE" "$SHA_FILE" "$PIN_FILE"
fi
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

# How long to wait for a pull request's checks to exist before giving up.
CHECKS_APPEAR_TIMEOUT="${CHECKS_APPEAR_TIMEOUT:-240}"

# Wait until a pull request actually has checks, before watching them.
#
# `gh pr checks --watch` exits 0 when a pull request has no checks at all: it
# prints "no checks reported" and returns success. Immediately after `pr create`
# the workflow has usually not registered yet, so a watch that starts in that
# window reports green for a run that never happened, and the next stage merges.
#
# This is not hypothetical. Opening a pull request here and watching it one
# second later returned exit 0 with no checks, and the run appeared seconds
# after that. The window is small, which is what makes it dangerous: it is a
# race that passes almost every time.
#
# Timing out is a failure, not a pass. A pull request that never registers a
# check has not been verified, and merging it would put an unverified commit on
# main and then into production.
await_checks() {
  local what="$1"; shift
  local waited=0 out
  while :; do
    out="$("$@" 2>&1 || true)"
    case "$out" in
      "" | *"no checks reported"*) : ;;
      *) return 0 ;;
    esac
    if [ "$waited" -ge "$CHECKS_APPEAR_TIMEOUT" ]; then
      die "$what registered no checks within ${CHECKS_APPEAR_TIMEOUT}s - refusing to treat an absent run as a pass"
    fi
    sleep 10
    waited=$((waited + 10))
  done
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
    record_release_commit
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
  record_release_commit
}

# The release commit is the PR head, recorded once. The pin is written from it
# before CI finishes, so it has to be the exact commit CI is testing, and it
# must not follow the branch if the branch moves.
record_release_commit() {
  [ -n "$OPERATIONS_SHA" ] && return 0
  OPERATIONS_SHA="$(git -C "$OPS_REPO" rev-parse "origin/$OPERATIONS_BRANCH")"
  [ "${#OPERATIONS_SHA}" -eq 40 ] || die "could not resolve the head of $OPERATIONS_BRANCH"
  printf '%s' "$OPERATIONS_SHA" > "$SHA_FILE"
  say "release commit is the PR head ${OPERATIONS_SHA:0:7}"
}

# The branch must still be where it was pinned. A push after the pin would have
# CI testing one commit while Marketing pins another.
require_pinned_head() {
  local head
  head="$(ops_gh pr view "$OPERATIONS_BRANCH" --json headRefOid -q .headRefOid 2>/dev/null || true)"
  [ "$head" = "$OPERATIONS_SHA" ] \
    || die "$OPERATIONS_BRANCH moved to ${head:0:7} after ${OPERATIONS_SHA:0:7} was pinned — re-run with --restart"
}

# ── ops_ci ──────────────────────────────────────────────────────────────────
run_ops_ci() {
  if [ -z "$OPERATIONS_BRANCH" ] || branch_is_merged; then
    say "nothing to poll"
    return 0
  fi
  require_pinned_head
  say "polling Operations checks"
  await_checks "Operations PR $OPERATIONS_BRANCH" ops_gh pr checks "$OPERATIONS_BRANCH"
  ops_gh pr checks "$OPERATIONS_BRANCH" --watch --interval 20 >/dev/null \
    || die "Operations CI did not pass — read the run before retrying"
  say "Operations CI green"
}

# ── ops_merge ───────────────────────────────────────────────────────────────
# Both CIs are green by the time this runs. Main is fast-forwarded to the pinned
# commit: pushed as-is and never forced, so the push is refused unless main is
# still an ancestor of it, and branch protection still requires its `ci` check.
# GitHub records the pull request as merged once its head lands on main.
#
# When main has moved since the branch was cut a fast-forward is impossible. The
# pull request is then merged with a merge commit, as before, and the pin is
# moved to that commit: pinning the head instead would ship the branch without
# whatever else had reached main, reverting it in production.
run_ops_merge() {
  if [ -n "$OPERATIONS_BRANCH" ] && ! branch_is_merged; then
    local state
    state="$(ops_gh pr view "$OPERATIONS_BRANCH" --json mergeStateStatus -q .mergeStateStatus 2>/dev/null || echo UNKNOWN)"
    # A conflicted branch needs a human: resolving it means choosing which side
    # of the change survives, which is not a decision to automate.
    [ "$state" = "DIRTY" ] && die "$OPERATIONS_BRANCH has a merge conflict — resolve it, then re-run"
    require_pinned_head
    git -C "$OPS_REPO" fetch --quiet origin main
    if git -C "$OPS_REPO" merge-base --is-ancestor origin/main "$OPERATIONS_SHA"; then
      git -C "$OPS_REPO" push --quiet origin "$OPERATIONS_SHA:refs/heads/main" \
        || die "Operations main refused the fast-forward to ${OPERATIONS_SHA:0:7}"
      await_merged
      git -C "$OPS_REPO" push --quiet origin --delete "$OPERATIONS_BRANCH" 2>/dev/null || true
      say "fast-forwarded Operations main to ${OPERATIONS_SHA:0:7}; merged $OPERATIONS_BRANCH"
    else
      local stale_pin merged
      stale_pin="$(pin_branch)"
      ops_gh pr merge "$OPERATIONS_BRANCH" --merge --delete-branch >/dev/null \
        || die "could not merge the Operations PR"
      merged="$(ops_gh pr view "$OPERATIONS_BRANCH" --json mergeCommit -q .mergeCommit.oid 2>/dev/null || true)"
      [ "${#merged}" -eq 40 ] || die "could not determine the merge commit for $OPERATIONS_BRANCH"
      OPERATIONS_SHA="$merged"
      printf '%s' "$OPERATIONS_SHA" > "$SHA_FILE"
      say "main had moved: merged $OPERATIONS_BRANCH as ${OPERATIONS_SHA:0:7}; re-pinning to it"
      gh pr close "$stale_pin" --delete-branch \
        --comment "Superseded by a pin of merge commit ${OPERATIONS_SHA:0:7}: main moved before the fast-forward." >/dev/null || true
      run_pin
      run_pin_ci
    fi
  fi
  if [ -z "$OPERATIONS_SHA" ]; then
    OPERATIONS_SHA="$(ops_gh pr view "$OPERATIONS_BRANCH" --json mergeCommit -q .mergeCommit.oid 2>/dev/null || true)"
    [ -n "$OPERATIONS_SHA" ] || die "could not determine the merge commit for $OPERATIONS_BRANCH"
    printf '%s' "$OPERATIONS_SHA" > "$SHA_FILE"
  fi
  say "Operations commit is ${OPERATIONS_SHA:0:7}"
}

# GitHub marks a pull request merged when its head reaches the base branch, a
# few seconds after the push. The branch is deleted only after that, so the pull
# request reads as merged rather than closed.
await_merged() {
  local waited=0 state
  while :; do
    state="$(ops_gh pr view "$OPERATIONS_BRANCH" --json state -q .state 2>/dev/null || echo UNKNOWN)"
    [ "$state" = MERGED ] && return 0
    [ "$waited" -ge 60 ] && die "main is at ${OPERATIONS_SHA:0:7} but GitHub has not marked the PR merged (state $state)"
    sleep 3
    waited=$((waited + 3))
  done
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
  printf '%s' "$(pin_branch)" > "$PIN_FILE"
  say "opened pin PR"
}

run_pin_ci() {
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then say "already pinned"; return 0; fi
  # Which lane the pin takes is decided in CI (scripts/ci_classify.sh), not
  # here: a pin of a frontend-only Operations range runs the compose and
  # contract checks, any other range adds dual-service, and Marketing's own
  # suite is skipped because a pin leaves every Marketing input unchanged. The
  # watch below still fails on any failing or missing check.
  say "polling pin checks"
  await_checks "pin PR $(pin_branch)" gh pr checks "$(pin_branch)"
  gh pr checks "$(pin_branch)" --watch --interval 20 >/dev/null \
    || die "pin CI did not pass — read the run before retrying"
  say "pin CI green"
}

run_pin_merge() {
  git -C "$HERE" fetch --quiet origin main
  if [ "$(current_anchor)" = "$OPERATIONS_SHA" ]; then say "anchor already on main"; return 0; fi
  # The pin was opened before Operations merged. Whatever happened since, it
  # may only land once its commit is on Operations main.
  git -C "$OPS_REPO" fetch --quiet origin main
  git -C "$OPS_REPO" merge-base --is-ancestor "$OPERATIONS_SHA" origin/main 2>/dev/null \
    || die "refusing to merge the pin: ${OPERATIONS_SHA:0:7} is not on Operations main"
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

# Is production already serving exactly what this run would produce?
#
# The recorded stage list makes a resumed run skip work, but that record is
# local: delete it and the script would rebuild and recreate a container that
# is already correct, costing a needless restart of a healthy service. This
# asks production directly, so the skip survives losing local state.
#
# All three conditions matter. Matching /version alone is not enough: a healthy
# container with no 8210 binding still serves 502 through nginx, and a
# container outside this compose project is not the one a deploy would replace.
production_matches_target() {
  [ -n "$OPERATIONS_SHA" ] || return 1
  "${SSH[@]}" bash -s -- "$OPERATIONS_SHA" "$COMPOSE_PROJECT" "$HEALTH_URL" <<'REMOTE' >/dev/null 2>&1
set -euo pipefail
WANT="$1"; PROJECT="$2"; HEALTH="$3"
GOT=$(curl -s -m 10 "$HEALTH/version" | sed -n 's/.*"sha":"\([0-9a-f]*\)".*/\1/p')
[ "$GOT" = "$WANT" ] || exit 1
PORTS=$(docker port "${PROJECT}-operations-api-1" 8000/tcp 2>/dev/null || true)
grep -q '127.0.0.1:8210' <<<"$PORTS" || exit 1
TOTAL=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Status}}' | wc -l)
OK=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Status}}' | grep -c healthy)
[ "$TOTAL" -gt 0 ] && [ "$OK" = "$TOTAL" ]
REMOTE
}

run_build() {
  if production_matches_target; then
    say "production already serves ${OPERATIONS_SHA:0:7}, bound and healthy — nothing to build"
    return 0
  fi
  "${SSH[@]}" "cd /opt/teleautomation/marketing && docker compose -p '$COMPOSE_PROJECT' \
    --env-file '$PROD_ENV_FILE' -f '$COMPOSE_FILE' build '$SERVICE'" >/dev/null || die "build failed"
  say "image built"
}

run_deploy() {
  if production_matches_target; then
    say "production already serves ${OPERATIONS_SHA:0:7}, bound and healthy — nothing to deploy"
    return 0
  fi
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
HEALTH_BODY=$(curl -s -m 10 "$HEALTH/health" || true)
grep -q '"status":"ok"' <<<"$HEALTH_BODY" || { echo "  health not ok" >&2; exit 1; }
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
  stage_started=$SECONDS
  "run_$stage"
  mark_done "$stage"
  say "($((SECONDS - stage_started))s)"
done

echo
echo "DONE — ${OPERATIONS_SHA:0:7} is live and verified. (${SECONDS}s)"
echo "Live behaviour still needs checking in the browser: a green deploy proves"
echo "the release is running, not that the change does what was asked."
