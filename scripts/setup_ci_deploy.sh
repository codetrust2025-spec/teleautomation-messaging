#!/usr/bin/env bash
# One-time setup for CI-driven production deploys.
#
# Run it yourself, once, from Git Bash on a machine where `gh` is logged in as
# the repository owner and you have root SSH access to the production host:
#
#   KVM1_SSH=root@<host> KVM1_SSH_KEY=~/.ssh/<key> bash scripts/setup_ci_deploy.sh
#   KVM1_SSH=root@<host> KVM1_SSH_KEY=~/.ssh/<key> bash scripts/setup_ci_deploy.sh --check
#
# `--check` reports what is already in place and changes nothing.
#
# It creates credentials and changes security settings, which is why it is a
# script a person runs rather than something an agent does:
#
#   1. a read-only deploy key on Marketing, whose private half becomes the
#      Operations secret MARKETING_READ_DEPLOY_KEY (the dual-service CI job);
#   2. branch protection on Operations main: a pull request and the `ci` check
#      are required, the branch must be up to date, the rules apply to admins,
#      and force-push and deletion are refused;
#   3. the Operations `production` environment, usable only from protected
#      branches, which after step 2 means main;
#   4. a production deploy key. Its public half provisions the host's `deploy`
#      user through deploy/production/provision_deploy_user.sh; its private half
#      becomes the environment secret PROD_DEPLOY_SSH_KEY; the host address and
#      the host key -- read over your already-trusted SSH connection, never from
#      an unauthenticated scan -- become environment variables.
#
# Both private keys are generated into a private temporary directory, handed to
# `gh secret set` on stdin, and deleted when the script exits, whether it
# succeeds or not. Neither is ever printed. Re-running replaces both keys.
set -euo pipefail
umask 077

OPS="${OPS_REPO_SLUG:-codetrust2025-spec/teleautomation-operations}"
MKT="${MKT_REPO_SLUG:-codetrust2025-spec/teleautomation-messaging}"
READ_KEY_TITLE="Operations CI (read-only)"
PROVISION="/opt/teleautomation/marketing/deploy/production/provision_deploy_user.sh"

say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
die()  { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }

MODE=apply
case "${1:-}" in
  "") ;;
  --check) MODE=check ;;
  *) die "unknown argument: $1 (expected nothing, or --check)" ;;
esac

: "${KVM1_SSH:?set KVM1_SSH=root@<production host>}"
HOST="${KVM1_SSH#*@}"
[ -n "$HOST" ] && [ "$HOST" != "$KVM1_SSH" ] || die "KVM1_SSH must look like root@<host>"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=20)
[ -n "${KVM1_SSH_KEY:-}" ] && SSH+=(-i "$KVM1_SSH_KEY")

for tool in gh ssh ssh-keygen; do
  command -v "$tool" >/dev/null || die "$tool is required"
done
gh auth status >/dev/null 2>&1 || die "gh is not logged in; run 'gh auth login' first"

# ── check ───────────────────────────────────────────────────────────────────
report() {
  local missing=0 line
  mark() { if [ "$1" = ok ]; then say "ok       $2"; else say "MISSING  $2"; missing=1; fi; }

  if gh variable list --repo "$OPS" 2>/dev/null | grep -q '^OPERATIONS_PUBLIC_URL' \
     && gh variable list --repo "$OPS" 2>/dev/null | grep -q '^MARKETING_PUBLIC_URL'; then
    mark ok "public URL variables"
  else
    mark missing "public URL variables"
  fi

  line="$(gh api "repos/$MKT/keys" --jq ".[] | select(.title == \"$READ_KEY_TITLE\") | .read_only" 2>/dev/null | head -1 || true)"
  if [ "$line" = true ] && gh secret list --repo "$OPS" 2>/dev/null | grep -q '^MARKETING_READ_DEPLOY_KEY'; then
    mark ok "read-only Marketing key and MARKETING_READ_DEPLOY_KEY"
  else
    mark missing "read-only Marketing key and MARKETING_READ_DEPLOY_KEY"
  fi

  line="$(gh api "repos/$OPS/branches/main/protection" \
    --jq '"\(.required_status_checks.strict) \(.required_status_checks.contexts | index("ci") != null) \(.enforce_admins.enabled) \(.allow_force_pushes.enabled)"' 2>/dev/null || true)"
  if [ "$line" = "true true true false" ]; then mark ok "branch protection on main"; else mark missing "branch protection on main"; fi

  line="$(gh api "repos/$OPS/environments/production" --jq '.deployment_branch_policy.protected_branches' 2>/dev/null || true)"
  if [ "$line" = true ]; then mark ok "production environment (protected branches only)"; else mark missing "production environment (protected branches only)"; fi

  if gh secret list --env production --repo "$OPS" 2>/dev/null | grep -q '^PROD_DEPLOY_SSH_KEY' \
     && gh variable list --env production --repo "$OPS" 2>/dev/null | grep -q '^PROD_DEPLOY_HOST' \
     && gh variable list --env production --repo "$OPS" 2>/dev/null | grep -q '^PROD_KNOWN_HOSTS'; then
    mark ok "production deploy key secret and host variables"
  else
    mark missing "production deploy key secret and host variables"
  fi

  if "${SSH[@]}" "$KVM1_SSH" 'id deploy >/dev/null 2>&1 && test -f /etc/sudoers.d/teleautomation-deploy && test -f /etc/teleautomation/operations-release.env' 2>/dev/null; then
    mark ok "host deploy user, sudo rule and recorded release"
  else
    mark missing "host deploy user, sudo rule and recorded release"
  fi
  return "$missing"
}

if [ "$MODE" = check ]; then
  step "current setup"
  report && say "everything is in place" || exit 1
  exit 0
fi

WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# ── 1. read-only key for the dual-service check ─────────────────────────────
step "read-only Marketing key"
for id in $(gh api "repos/$MKT/keys" --jq ".[] | select(.title == \"$READ_KEY_TITLE\") | .id"); do
  gh api -X DELETE "repos/$MKT/keys/$id" >/dev/null
  say "removed the previous key $id"
done
ssh-keygen -q -t ed25519 -N "" -C "operations-ci-read-marketing" -f "$WORK/marketing_read"
# No --allow-write: GitHub creates deploy keys read-only unless asked otherwise.
gh repo deploy-key add "$WORK/marketing_read.pub" --repo "$MKT" --title "$READ_KEY_TITLE" >/dev/null
gh secret set MARKETING_READ_DEPLOY_KEY --repo "$OPS" < "$WORK/marketing_read" >/dev/null
rm -f "$WORK/marketing_read" "$WORK/marketing_read.pub"
say "added a read-only key to $MKT and stored its private half as MARKETING_READ_DEPLOY_KEY"

# ── 2. branch protection ────────────────────────────────────────────────────
step "branch protection on $OPS main"
gh api -X PUT "repos/$OPS/branches/main/protection" --input - >/dev/null <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["ci"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
say "PR and the ci check required, up to date with main, applies to admins"

# ── 3. production environment ──────────────────────────────────────────────
step "production environment"
gh api -X PUT "repos/$OPS/environments/production" --input - >/dev/null <<'JSON'
{"deployment_branch_policy": {"protected_branches": true, "custom_branch_policies": false}}
JSON
say "usable only from protected branches"

# ── 4. production deploy key and host user ──────────────────────────────────
step "production deploy key and host user"
ssh-keygen -q -t ed25519 -N "" -C "github-actions-production-deploy" -f "$WORK/prod_deploy"
"${SSH[@]}" "$KVM1_SSH" "bash $PROVISION" < "$WORK/prod_deploy.pub"

# The host key comes over the connection you already trust, so the pinned key
# cannot be one an attacker on the network substituted.
hostkey="$("${SSH[@]}" "$KVM1_SSH" 'cut -d" " -f1,2 /etc/ssh/ssh_host_ed25519_key.pub')"
[[ "$hostkey" =~ ^ssh-ed25519\ [A-Za-z0-9+/]+=*$ ]] || die "could not read the host's ed25519 key"

# Prove the key works exactly as intended before GitHub is given it: it reaches
# the forced command, and the forced command refuses anything that is not one
# of its verbs. A key that could do more is never stored.
printf '%s %s\n' "$HOST" "$hostkey" > "$WORK/known_hosts"
DEPLOY_SSH=(ssh -i "$WORK/prod_deploy" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20
            -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$WORK/known_hosts" "deploy@$HOST")
"${DEPLOY_SSH[@]}" status || die "the deploy key did not reach teleautomation-deploy status"
if "${DEPLOY_SSH[@]}" id >/dev/null 2>&1; then
  die "the deploy key ran an arbitrary command; the forced command is not in effect"
fi
say "the deploy key runs teleautomation-deploy and nothing else"

gh secret set PROD_DEPLOY_SSH_KEY --env production --repo "$OPS" < "$WORK/prod_deploy" >/dev/null
gh variable set PROD_DEPLOY_HOST --env production --repo "$OPS" --body "$HOST" >/dev/null
gh variable set PROD_KNOWN_HOSTS --env production --repo "$OPS" --body "$HOST $hostkey" >/dev/null
say "stored PROD_DEPLOY_SSH_KEY, PROD_DEPLOY_HOST and PROD_KNOWN_HOSTS in the production environment"
rm -f "$WORK/prod_deploy" "$WORK/prod_deploy.pub" "$WORK/known_hosts"

step "result"
report || die "some items are still missing (see above)"
say "setup complete; both private keys have been deleted from this machine"
