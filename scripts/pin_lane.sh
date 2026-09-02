#!/usr/bin/env bash
# Is this Marketing change nothing but a release pin? Reads changed paths on
# stdin, one per line, and prints `pin` or `full`.
#
# A pin PR is written by scripts/fix_and_deploy.sh and touches exactly two
# files: the release anchor in docker-compose.production.yml and the same SHA in
# tests/test_production_compose_contract.py. Nothing else in Marketing changes,
# so Marketing's own suite, dashboard, image build, container health, migration
# and persistence checks are all running against unchanged inputs.
#
# Answering `pin` only decides that MARKETING is unchanged. It does not on its
# own decide that the cross-service checks can be skipped -- that depends on
# what changed in Operations between the two anchors, which the workflow
# classifies separately using the Operations repository's own scripts/ci_lane.sh.
#
# Allowlist, so it is fail-safe: any third file, any other path, or an empty
# list is `full`.
set -uo pipefail

COMPOSE='docker-compose.production.yml'
CONTRACT='tests/test_production_compose_contract.py'

lane=pin
seen_compose=0
seen_contract=0
seen_any=0

# `|| [ -n "$path" ]` keeps a final line that has no trailing newline; without
# it `read` drops it, and a disqualifying path could be lost.
while IFS= read -r path || [ -n "$path" ]; do
  path="$(printf '%s' "$path" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  [ -z "$path" ] && continue
  seen_any=1
  case "$path" in
    "$COMPOSE")  seen_compose=1 ;;
    "$CONTRACT") seen_contract=1 ;;
    *)
      echo "full lane: $path is not part of a release pin" >&2
      lane=full
      break
      ;;
  esac
done

if [ "$seen_any" = 0 ]; then
  echo "full lane: no changed paths were supplied" >&2
  lane=full
fi

# Both files move in the same commit by design: the anchor and the test that
# asserts it must never disagree, or a build could be pinned to a commit the
# contract still expects to be the previous one. Seeing only one of them is not
# the shape fix_and_deploy.sh produces, so it is not treated as a pin.
if [ "$lane" = pin ] && { [ "$seen_compose" = 0 ] || [ "$seen_contract" = 0 ]; }; then
  echo "full lane: a pin moves both the anchor and the contract test together" >&2
  lane=full
fi

printf '%s\n' "$lane"
