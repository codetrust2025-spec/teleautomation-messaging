#!/usr/bin/env bash
# One-time host setup for CI deploys. Run as root on the production host, with
# the deploy key's PUBLIC half on stdin:
#
#   ssh root@<host> 'bash /opt/teleautomation/marketing/deploy/production/provision_deploy_user.sh' < prod_deploy_key.pub
#
# What it does, and nothing more:
#   - creates a `deploy` system user whose SSH key can only run
#     /usr/local/sbin/teleautomation-deploy (forced command + `restrict`: no
#     shell, no pty, no port, agent or X11 forwarding);
#   - allows that user to run exactly that one script as root through sudo;
#   - installs teleautomation-deploy and teleautomation-compose from this
#     checkout, owned by root and not writable by `deploy`;
#   - records the currently running Operations container as the first release,
#     so the first CI deploy has something verified to roll back to.
#
# It changes no running container and reads no secret. Re-running it replaces
# the key and reinstalls the scripts; the recorded release is kept.
set -euo pipefail

die() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"

HERE="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_USER=deploy
SCRIPT=/usr/local/sbin/teleautomation-deploy
WRAPPER=/usr/local/sbin/teleautomation-compose
SUDOERS=/etc/sudoers.d/teleautomation-deploy

IFS= read -r pubkey || true
[[ "$pubkey" =~ ^ssh-ed25519\ [A-Za-z0-9+/]+=*(\ [^[:space:]]+)?$ ]] \
  || die "stdin must be exactly one ssh-ed25519 public key line (the .pub file, never the private key)"

# sshd must be willing to let the new user in at all.
sshd_config="$(sshd -T 2>/dev/null || true)"
if grep -Eiq '^allowusers ' <<<"$sshd_config"; then
  grep -Ei '^allowusers ' <<<"$sshd_config" | grep -w "$DEPLOY_USER" >/dev/null \
    || die "sshd AllowUsers does not include '$DEPLOY_USER'; add it deliberately before provisioning"
fi

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$DEPLOY_USER" --shell /bin/bash "$DEPLOY_USER"
  echo "  created user $DEPLOY_USER"
fi
# No password: the account is reachable only through the forced-command key.
passwd -l "$DEPLOY_USER" >/dev/null

install -o root -g root -m 0755 "$HERE/teleautomation-deploy" "$SCRIPT"
install -o root -g root -m 0755 "$HERE/teleautomation-compose" "$WRAPPER"
echo "  installed $SCRIPT and $WRAPPER"

# Root owns the key file, so the account cannot edit away its own restrictions.
install -d -o root -g root -m 0755 "/home/$DEPLOY_USER/.ssh"
keyfile_tmp="$(mktemp "/home/$DEPLOY_USER/.ssh/.authorized_keys.XXXXXX")"
printf 'command="%s",restrict %s\n' "$SCRIPT" "$pubkey" > "$keyfile_tmp"
chmod 0644 "$keyfile_tmp"
mv -f "$keyfile_tmp" "/home/$DEPLOY_USER/.ssh/authorized_keys"
echo "  installed the forced-command key for $DEPLOY_USER"

sudo_tmp="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: %s\n' "$DEPLOY_USER" "$SCRIPT" > "$sudo_tmp"
chmod 0440 "$sudo_tmp"
visudo -cf "$sudo_tmp" >/dev/null || { rm -f "$sudo_tmp"; die "the sudoers rule did not validate"; }
mv -f "$sudo_tmp" "$SUDOERS"
echo "  allowed $DEPLOY_USER to run only $SCRIPT as root"

install -d -o root -g root -m 0755 /etc/teleautomation
"$SCRIPT" init
"$SCRIPT" status || true

echo
echo "Host key for the PROD_KNOWN_HOSTS variable (put the address the workflow"
echo "connects to in place of HOST):"
printf '  HOST %s\n' "$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
