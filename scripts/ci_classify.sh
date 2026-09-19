#!/usr/bin/env bash
# Which lane a Marketing CI run takes. Run from the root of a full-history
# checkout of the commit under test; prints `lane=<lane>` and, in Actions,
# writes the same line to $GITHUB_OUTPUT. It always exits 0: the workflow's
# next step fails the run on any lane it does not recognise.
#
#   full      Marketing itself changed: Marketing's suite, image and container
#             checks (verify) and the cross-service checks (dual-service).
#   pin-dual  A release pin of an Operations range that is not frontend-only.
#             Marketing is unchanged, so verify would re-run identical inputs;
#             the cross-service checks still run against the new Operations.
#   pin       A release pin of an Operations range that both the lane rule in
#             production and the lane rule being pinned call frontend-only,
#             and that does not change the rule itself; or the push of
#             a pin that already passed on its pull request with the same tree:
#             the compose and release-contract checks only.
#
# Inputs, from the environment:
#   EVENT        github.event_name
#   BASE         pull_request base sha            (pull_request)
#   BEFORE       previous main head of the push   (push)
#   REPO         owner/name of this repository    (push: checks of the merged PR)
#   REPO_TOKEN   token that may read this repository's check runs
#   PEER         owner/name of the Operations repository
#   PEER_TOKEN   token that may read the Operations repository
#
# Fail-safe throughout: whatever cannot be established takes the lane that
# checks more. A Marketing diff that is not exactly a pin is always `full`; an
# Operations range that cannot be read is `pin-dual`, never `pin`.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EVENT="${EVENT:-}"
PEER="${PEER:-codetrust2025-spec/teleautomation-business}"

decide() {
  printf 'lane=%s\n' "$1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then printf 'lane=%s\n' "$1" >> "$GITHUB_OUTPUT"; fi
  printf '::notice::lane=%s (%s)\n' "$1" "$2"
  exit 0
}

anchor_at() {
  git show "$1:docker-compose.production.yml" 2>/dev/null \
    | sed -n 's/.*operations: &operations-release \([0-9a-f]\{40\}\).*/\1/p' | head -1
}

# require_pin <previous commit> <git diff arguments...>
#
# Is the change nothing but a release pin, with an anchor that moved from the
# one in <previous commit>? Sets OLD and NEW; any other answer ends the
# classification as `full`.
#
# From git rather than `gh api .../pulls/N/files`: that needs
# `pull-requests: read`, which the workflow token was refused, and the first
# pin classified that way saw an empty file list and fell back to full forever.
require_pin() {
  local previous="$1" files shape
  shift
  files=$(git diff --name-only "$@") || decide full "could not diff the change under test"
  echo "changed files:"; printf '%s\n' "$files" | sed 's/^/  /'
  shape=$(printf '%s\n' "$files" | bash "$HERE/pin_lane.sh")
  [ "$shape" = pin ] || decide full "Marketing change is not a pin"
  OLD=$(anchor_at "$previous")
  NEW=$(anchor_at HEAD)
  echo "anchor $OLD -> $NEW"
  { [ -n "$OLD" ] && [ -n "$NEW" ]; } || decide full "could not read both anchors"
  [ "$OLD" != "$NEW" ] || decide full "anchor did not move"
}

# The lane a pin of OLD..NEW needs, from what that Operations range changed and
# Operations' own lane rule, scripts/ci_lane.sh.
#
# The rule is read at both ends of the range and both must say frontend. Asking
# only NEW let the change under review decide how much of it was checked: a
# commit loosening the rule would have been judged by the loosened rule. OLD is
# the rule already in production, so it is the one a change cannot write. A
# range that edits the rule is never fast-laned at all.
range_lane() {
  local files rule ops at
  [ -n "${PEER_TOKEN:-}" ] || decide pin-dual "no peer token, cannot inspect the Operations range"
  files=$(GH_TOKEN="$PEER_TOKEN" gh api "repos/$PEER/compare/$OLD...$NEW" --jq '.files[].filename') \
    || decide pin-dual "could not compare the Operations range"
  [ -n "$files" ] || decide pin-dual "Operations compare returned no files"
  echo "operations files in ${OLD:0:7}..${NEW:0:7}:"; printf '%s\n' "$files" | sed 's/^/  /'
  if printf '%s\n' "$files" | tr -d '\r' | grep -qxF 'scripts/ci_lane.sh'; then
    decide pin-dual "Operations range changes the lane rule itself"
  fi
  for at in "$OLD" "$NEW"; do
    rule=$(GH_TOKEN="$PEER_TOKEN" gh api "repos/$PEER/contents/scripts/ci_lane.sh?ref=$at" --jq '.content' \
      | base64 -d) || decide pin-dual "could not fetch the Operations lane rule at ${at:0:7}"
    [ -n "$rule" ] || decide pin-dual "Operations lane rule at ${at:0:7} was empty"
    ops=$(printf '%s\n' "$files" | bash -c "$rule")
    [ "$ops" = frontend ] || decide pin-dual "Operations range is ${ops:-unclassified} under the rule at ${at:0:7}"
  done
  decide pin "pin of a frontend-only Operations range"
}

# Did the pull request whose head is $1 pass this workflow? The latest attempt
# of each job must have completed: `ci` successfully, verify and dual-service
# successfully or skipped by their lane. A job that is missing, still running,
# failed, cancelled or never started is not a pass.
pull_request_passed() {
  local lines name status conclusion seen=""
  { [ -n "${REPO:-}" ] && [ -n "${REPO_TOKEN:-}" ]; } || return 1
  lines=$(GH_TOKEN="$REPO_TOKEN" gh api "repos/$REPO/commits/$1/check-runs?per_page=100" \
    --jq '[.check_runs[] | select(.app.slug == "github-actions")] | group_by(.name) | map(max_by(.id)) | .[] | "\(.name) \(.status) \(.conclusion)"') \
    || return 1
  echo "checks on ${1:0:7}:"; printf '%s\n' "$lines" | sed 's/^/  /'
  while read -r name status conclusion; do
    case "$name" in
      ci)
        [ "$status $conclusion" = "completed success" ] || return 1
        seen="$seen ci" ;;
      verify|dual-service)
        case "$status $conclusion" in
          "completed success"|"completed skipped") seen="$seen $name" ;;
          *) return 1 ;;
        esac ;;
    esac
  done <<< "$lines"
  case "$seen" in *" ci"*) ;; *) return 1 ;; esac
  case "$seen" in *" verify"*) ;; *) return 1 ;; esac
  case "$seen" in *" dual-service"*) ;; *) return 1 ;; esac
}

case "$EVENT" in
  pull_request)
    [ -n "${BASE:-}" ] || decide full "no pull request base"
    require_pin "$BASE" "$BASE...HEAD"
    range_lane
    ;;

  push)
    { [ -n "${BEFORE:-}" ] && [ -n "${BEFORE//0/}" ] && git cat-file -e "$BEFORE^{commit}" 2>/dev/null; } \
      || decide full "no previous main commit to compare with"
    require_pin "$BEFORE" "$BEFORE" HEAD
    # The merge of a pin that already passed: a merge commit whose first parent
    # is the previous main and whose second parent -- the pull request head --
    # is one commit on top of that same main. Its tree is then exactly the tree
    # the pull request run checked out, so the checks that passed there are the
    # checks of this commit, and re-running them only spends minutes.
    read -r _ P1 P2 EXTRA <<< "$(git rev-list --parents -n 1 HEAD)"
    if [ -n "${P2:-}" ] && [ -z "${EXTRA:-}" ] && [ "$P1" = "$BEFORE" ] \
       && [ "$(git rev-parse "$P2^" 2>/dev/null)" = "$BEFORE" ] && git diff --quiet "$P2" HEAD \
       && pull_request_passed "$P2"; then
      decide pin "merge of a pin that passed on its pull request with the same tree"
    fi
    range_lane
    ;;

  *)
    decide full "event is ${EVENT:-unknown}"
    ;;
esac
