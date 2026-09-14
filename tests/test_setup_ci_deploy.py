"""scripts/setup_ci_deploy.sh, run for real against stub gh, ssh and ssh-keygen.

The script creates two private keys and several security settings, so these
tests hold it to the properties that matter: private keys reach GitHub only on
stdin and never appear in output or in any command line, they are deleted even
when a step fails, each setting has exactly the intended value, and --check
changes nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup_ci_deploy.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or (sys.platform == "win32" and not os.environ.get("RUN_POSIX_SCRIPT_TESTS")),
    reason="the setup script is exercised with a POSIX bash and stub tools",
)

OPS = "codetrust2025-spec/teleautomation-operations"
MKT = "codetrust2025-spec/teleautomation-messaging"
HOST = "203.0.113.10"
HOSTKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHOSTKEYHOSTKEYHOSTKEYHOSTKEYHOSTKEYHOST"

GH = r"""#!/usr/bin/env bash
log="$STUB_DIR/calls.log"
printf 'gh %s\n' "$*" >> "$log"
all="${STUB_ALL_PRESENT:-0}"
case "$1 $2" in
  "auth status") exit 0 ;;
  "secret set")
    name="$3"; cat > "$STUB_DIR/secret_$name"
    printf '%s\n' "$*" > "$STUB_DIR/secret_${name}.args"
    exit 0 ;;
  "secret list")
    [ "$all" = 1 ] || exit 0
    case " $* " in
      *" --env production "*) printf 'PROD_DEPLOY_SSH_KEY\t2026-09-14\n' ;;
      *) printf 'MARKETING_READ_DEPLOY_KEY\t2026-09-14\n' ;;
    esac
    exit 0 ;;
  "variable set")
    name="$3"; shift 3
    while [ $# -gt 0 ]; do [ "$1" = "--body" ] && printf '%s' "$2" > "$STUB_DIR/var_$name"; shift; done
    exit 0 ;;
  "variable list")
    [ "$all" = 1 ] || exit 0
    case " $* " in
      *" --env production "*) printf 'PROD_DEPLOY_HOST\tx\nPROD_KNOWN_HOSTS\tx\n' ;;
      *) printf 'MARKETING_PUBLIC_URL\tx\nOPERATIONS_PUBLIC_URL\tx\n' ;;
    esac
    exit 0 ;;
  "repo deploy-key")
    printf '%s\n' "$*" > "$STUB_DIR/deploy_key_add.args"
    exit 0 ;;
  "api -X")
    method="$3"; path="$4"
    case "$method $path" in
      "PUT repos/$OPS_SLUG/branches/main/protection") cat > "$STUB_DIR/protection.json" ;;
      "PUT repos/$OPS_SLUG/environments/production") cat > "$STUB_DIR/environment.json" ;;
      "DELETE "*) : ;;
    esac
    exit 0 ;;
  "api repos/$MKT_SLUG/keys")
    case "$*" in
      *read_only*) [ "$all" = 1 ] && printf 'true\n' ;;
      *".id"*) [ -n "${STUB_EXISTING_KEY_ID:-}" ] && printf '%s\n' "$STUB_EXISTING_KEY_ID" ;;
    esac
    exit 0 ;;
  "api repos/$OPS_SLUG/branches/main/protection") [ "$all" = 1 ] && printf 'true true true false\n'; exit 0 ;;
  "api repos/$OPS_SLUG/environments/production") [ "$all" = 1 ] && printf 'true\n'; exit 0 ;;
esac
exit 0
"""

SSH = r"""#!/usr/bin/env bash
printf 'ssh %s\n' "$*" >> "$STUB_DIR/calls.log"
cmd="${*: -1}"
case "$*" in
  *"deploy@"*)
    printf '%s\n' "$*" >> "$STUB_DIR/deploy_ssh.args"
    case "$cmd" in
      status) printf '  serving: aaaaaaa\n'; exit 0 ;;
      *) exit "${STUB_FORCED_COMMAND_EXIT:-2}" ;;
    esac ;;
esac
case "$cmd" in
  *provision_deploy_user.sh*)
    cat > "$STUB_DIR/provision_stdin"
    exit "${STUB_PROVISION_EXIT:-0}" ;;
  *ssh_host_ed25519_key.pub*) printf '%s\n' "$STUB_HOSTKEY"; exit 0 ;;
  *"id deploy"*) [ "${STUB_ALL_PRESENT:-0}" = 1 ] && exit 0 || exit 1 ;;
esac
exit 0
"""

KEYGEN = r"""#!/usr/bin/env bash
file=""; comment=""
while [ $# -gt 0 ]; do
  case "$1" in -f) file="$2"; shift ;; -C) comment="$2"; shift ;; esac
  shift
done
printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\nPRIVATE-MATERIAL-%s\n-----END OPENSSH PRIVATE KEY-----\n' "$comment" > "$file"
printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPUBLIC%s %s\n' "$(printf '%s' "$comment" | tr -dc 'A-Za-z')" "$comment" > "$file.pub"
"""


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture()
def pc(tmp_path: Path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _write(stubs / "gh", GH)
    _write(stubs / "ssh", SSH)
    _write(stubs / "ssh-keygen", KEYGEN)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()

    base = {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmpdir),
        "STUB_DIR": str(tmp_path),
        "STUB_HOSTKEY": HOSTKEY,
        "OPS_SLUG": OPS,
        "MKT_SLUG": MKT,
        "KVM1_SSH": f"root@{HOST}",
    }

    class PC:
        path = tmp_path
        temp = tmpdir

        def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["bash", str(SCRIPT), *args], text=True, capture_output=True,
                env={**base, **extra}, timeout=60,
            )

        def calls(self) -> str:
            log = tmp_path / "calls.log"
            return log.read_text(encoding="utf-8") if log.exists() else ""

        def read(self, name: str) -> str:
            return (tmp_path / name).read_text(encoding="utf-8")

    return PC()


MUTATIONS = ("secret set", "variable set", "deploy-key add", "-X PUT", "-X DELETE", "provision_deploy_user.sh")


class TestApply:
    def test_it_completes_and_proves_the_deploy_key_is_restricted(self, pc):
        result = pc.run(STUB_ALL_PRESENT="1")
        assert result.returncode == 0, result.stderr
        assert "runs teleautomation-deploy and nothing else" in result.stdout
        assert "setup complete" in result.stdout

    def test_private_keys_reach_github_on_stdin_only(self, pc):
        result = pc.run(STUB_ALL_PRESENT="1")
        assert result.returncode == 0, result.stderr
        assert "PRIVATE-MATERIAL-operations-ci-read-marketing" in pc.read("secret_MARKETING_READ_DEPLOY_KEY")
        assert "PRIVATE-MATERIAL-github-actions-production-deploy" in pc.read("secret_PROD_DEPLOY_SSH_KEY")
        assert "--env production" in pc.read("secret_PROD_DEPLOY_SSH_KEY.args")
        for text in (result.stdout, result.stderr, pc.calls()):
            assert "PRIVATE-MATERIAL" not in text

    def test_no_key_file_survives_the_run(self, pc):
        result = pc.run(STUB_ALL_PRESENT="1")
        assert result.returncode == 0, result.stderr
        assert list(pc.temp.iterdir()) == []

    def test_no_key_file_survives_a_failed_run(self, pc):
        result = pc.run(STUB_ALL_PRESENT="1", STUB_PROVISION_EXIT="1")
        assert result.returncode != 0
        assert list(pc.temp.iterdir()) == []
        assert not (pc.path / "secret_PROD_DEPLOY_SSH_KEY").exists()

    def test_the_marketing_key_is_read_only(self, pc):
        assert pc.run(STUB_ALL_PRESENT="1").returncode == 0
        args = pc.read("deploy_key_add.args")
        assert f"--repo {MKT}" in args
        assert "--allow-write" not in args and " -w" not in args

    def test_a_rerun_replaces_the_previous_read_key(self, pc):
        assert pc.run(STUB_ALL_PRESENT="1", STUB_EXISTING_KEY_ID="4242").returncode == 0
        assert f"gh api -X DELETE repos/{MKT}/keys/4242" in pc.calls()

    def test_branch_protection_has_exactly_the_agreed_rules(self, pc):
        assert pc.run(STUB_ALL_PRESENT="1").returncode == 0
        rules = json.loads(pc.read("protection.json"))
        assert rules["required_status_checks"] == {"strict": True, "contexts": ["ci"]}
        assert rules["enforce_admins"] is True
        assert rules["required_pull_request_reviews"] == {"required_approving_review_count": 0}
        assert rules["allow_force_pushes"] is False and rules["allow_deletions"] is False

    def test_the_environment_accepts_only_protected_branches(self, pc):
        assert pc.run(STUB_ALL_PRESENT="1").returncode == 0
        policy = json.loads(pc.read("environment.json"))["deployment_branch_policy"]
        assert policy == {"protected_branches": True, "custom_branch_policies": False}

    def test_the_host_key_is_pinned_from_the_trusted_connection(self, pc):
        assert pc.run(STUB_ALL_PRESENT="1").returncode == 0
        assert pc.read("var_PROD_KNOWN_HOSTS") == f"{HOST} {HOSTKEY}"
        assert pc.read("var_PROD_DEPLOY_HOST") == HOST
        assert "ssh-keyscan" not in SCRIPT.read_text(encoding="utf-8")
        assert "StrictHostKeyChecking=yes" in pc.read("deploy_ssh.args")

    def test_the_host_receives_only_the_public_key(self, pc):
        assert pc.run(STUB_ALL_PRESENT="1").returncode == 0
        sent = pc.read("provision_stdin")
        assert sent.startswith("ssh-ed25519 ")
        assert "PRIVATE" not in sent

    def test_a_key_that_can_run_arbitrary_commands_fails_the_setup(self, pc):
        result = pc.run(STUB_ALL_PRESENT="1", STUB_FORCED_COMMAND_EXIT="0")
        assert result.returncode != 0
        assert "forced command is not in effect" in result.stderr
        assert list(pc.temp.iterdir()) == []
        assert not (pc.path / "secret_PROD_DEPLOY_SSH_KEY").exists()


class TestCheck:
    def test_it_changes_nothing_and_reports_what_is_missing(self, pc):
        result = pc.run("--check")
        assert result.returncode != 0
        assert "MISSING" in result.stdout
        for mutation in MUTATIONS:
            assert mutation not in pc.calls()

    def test_it_passes_when_everything_is_in_place(self, pc):
        result = pc.run("--check", STUB_ALL_PRESENT="1")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "MISSING" not in result.stdout
        for mutation in MUTATIONS:
            assert mutation not in pc.calls()

    def test_an_unknown_argument_is_refused(self, pc):
        assert pc.run("--force").returncode != 0
        assert pc.calls() == ""
