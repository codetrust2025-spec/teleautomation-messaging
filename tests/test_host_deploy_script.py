"""deploy/production/teleautomation-deploy, driven for real against stub tools.

The script is the only thing the CI deploy key can run on the production host,
so these tests exercise the script itself -- its argument validation, its SSH
entry, its registry handling, its restart, verification and rollback -- with
`docker`, `curl`, `sudo`, `flock` and `ps` replaced by small fakes on PATH.
Nothing here touches Docker or the network.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "production" / "teleautomation-deploy"
WRAPPER = ROOT / "deploy" / "production" / "teleautomation-compose"
PROVISION = ROOT / "deploy" / "production" / "provision_deploy_user.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or (sys.platform == "win32" and not os.environ.get("RUN_POSIX_SCRIPT_TESTS")),
    reason="the host deploy script is exercised with a POSIX bash and stub tools",
)

SHA = "a" * 40
OTHER_SHA = "b" * 40
DIGEST = "sha256:" + "c" * 64
REPO = "ghcr.io/codetrust2025-spec/teleautomation-operations"
REF = f"{REPO}@{DIGEST}"
TOKEN = "ghs_test_registry_token_must_never_appear"

DOCKER_STUB = r"""#!/usr/bin/env bash
# Fake docker. Every call is appended to $STUB_DIR/docker.log, one per line.
printf '%s\n' "$*" >> "$STUB_DIR/docker.log"
state="$STUB_DIR/state"; mkdir -p "$state"
image_id() { printf 'sha256:id-%s\n' "$(printf '%s' "$1" | tr -c 'A-Za-z0-9' '_')"; }

args=("$@")
if [ "${args[0]}" = "--config" ]; then args=("${args[@]:2}"); fi

case "${args[0]} ${args[1]:-}" in
  "login "*)
    read -r supplied || true
    [ "$supplied" = "${STUB_EXPECT_TOKEN:-}" ] || exit 1
    exit 0 ;;
  "logout "*) exit 0 ;;
  "pull "*) exit "${STUB_PULL_EXIT:-0}" ;;
  "tag "*) exit 0 ;;
  "image inspect")
    ref="${args[2]}"; format="${args[4]:-}"
    case " ${STUB_MISSING_IMAGES:-} " in *" $ref "*) exit 1 ;; esac
    case "$format" in
      *revision*) printf '%s\n' "${STUB_LABEL_REVISION:-}" ;;
      *Env*) printf 'PATH=/usr/bin\nRELEASE_SHA=%s\n' "${STUB_BAKED_SHA:-}" ;;
      *Id*) image_id "$ref" ;;
    esac
    exit 0 ;;
  "inspect "*)
    format="${args[3]:-}"
    case "$format" in
      *Health*) printf '%s\n' "${STUB_HEALTH:-healthy}" ;;
      *Image*) cat "$state/running_image" 2>/dev/null || printf '%s\n' "${STUB_RUNNING_IMAGE:-}" ;;
    esac
    exit 0 ;;
  "port "*) printf '127.0.0.1:8210\n'; exit 0 ;;
  "ps "*) for _ in 1 2 3 4; do printf 'Up 1 minute (healthy)\n'; done; exit 0 ;;
  "compose "*)
    envfiles=(); prev=""
    for a in "${args[@]}"; do
      [ "$prev" = "--env-file" ] && envfiles+=("$a")
      prev="$a"
    done
    last="${envfiles[${#envfiles[@]}-1]}"
    image="$(sed -n 's/^OPERATIONS_IMAGE=//p' "$last" 2>/dev/null | head -1)"
    case " ${args[*]} " in
      *" config --images"*)
        if [ "${STUB_COMPOSE_READS_IMAGE:-1}" = 1 ] && [ -n "$image" ]; then
          printf 'postgres:16\n%s\n' "$image"
        else
          printf 'postgres:16\nteleautomation-production-operations-api\n'
        fi
        exit 0 ;;
      *" up "*)
        [ "${STUB_UP_EXIT:-0}" = 0 ] || exit "$STUB_UP_EXIT"
        sha="$(sed -n 's/^OPERATIONS_RELEASE_SHA=//p' "$last" | head -1)"
        image_id "$image" > "$state/running_image"
        if [ -n "${STUB_BROKEN_SHA:-}" ] && [ "$sha" = "$STUB_BROKEN_SHA" ]; then
          printf '%s\n' "0000000000000000000000000000000000000000" > "$state/served_sha"
        else
          printf '%s\n' "$sha" > "$state/served_sha"
        fi
        exit 0 ;;
    esac
    exit 0 ;;
esac
exit 0
"""

CURL_STUB = r"""#!/usr/bin/env bash
printf 'curl %s\n' "$*" >> "$STUB_DIR/docker.log"
state="$STUB_DIR/state"
for a in "$@"; do
  case "$a" in
    */version) printf '{"service":"teleautomation-operations","sha":"%s"}' "$(cat "$state/served_sha" 2>/dev/null || printf '%s' "${STUB_SERVED_SHA:-}")"; exit 0 ;;
    */health) printf '{"status":"ok"}'; exit 0 ;;
  esac
done
printf '%s' "${STUB_PUBLIC_CODE:-200}"
"""


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture()
def host(tmp_path: Path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _write(stubs / "docker", DOCKER_STUB)
    _write(stubs / "curl", CURL_STUB)
    _write(stubs / "id", '#!/usr/bin/env bash\nif [ "$1" = "-u" ]; then echo "${STUB_UID:-0}"; else exec /usr/bin/id "$@"; fi\n')
    _write(stubs / "sudo", '#!/usr/bin/env bash\nprintf "sudo %s\\n" "$*" >> "$STUB_DIR/docker.log"\n')
    _write(stubs / "flock", "#!/usr/bin/env bash\nexit 0\n")
    _write(stubs / "ps", '#!/usr/bin/env bash\nprintf "%s" "${STUB_PS:-}"\n')
    _write(stubs / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    etc = tmp_path / "etc"
    etc.mkdir()
    (tmp_path / "prod.env").write_text("SECRET=never-read-by-tests\n", encoding="utf-8")
    (tmp_path / "docker-compose.production.yml").write_text("services: {}\n", encoding="utf-8")

    env = {
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "STUB_DIR": str(tmp_path),
        "STUB_EXPECT_TOKEN": TOKEN,
        "STUB_LABEL_REVISION": SHA,
        "STUB_BAKED_SHA": SHA,
        "TA_COMPOSE_DIR": str(tmp_path),
        "TA_ENV_FILE": str(tmp_path / "prod.env"),
        "TA_RELEASE_DIR": str(etc),
        "TA_LOCK_FILE": str(tmp_path / "deploy.lock"),
        "TA_LOG_FILE": str(tmp_path / "deploy.log"),
        "TA_HEALTH_WAIT_SECONDS": "4",
        "TA_POLL_SECONDS": "1",
        "TA_SELF": str(SCRIPT),
    }

    class Host:
        path = tmp_path
        release = etc / "operations-release.env"
        previous = etc / "operations-release.previous.env"

        def run(self, *args: str, stdin: str = "", **extra: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["bash", str(SCRIPT), *args], input=stdin, text=True,
                capture_output=True, env={**env, **extra}, timeout=60,
            )

        def calls(self) -> str:
            log = tmp_path / "docker.log"
            return log.read_text(encoding="utf-8") if log.exists() else ""

        def record(self, target: Path, image: str, sha: str, digest: str = "") -> None:
            target.write_text(
                f"OPERATIONS_IMAGE={image}\nOPERATIONS_RELEASE_SHA={sha}\nOPERATIONS_RELEASE_DIGEST={digest}\n",
                encoding="utf-8",
            )

        def serving(self, sha: str, image: str) -> None:
            state = tmp_path / "state"
            state.mkdir(exist_ok=True)
            (state / "served_sha").write_text(sha + "\n", encoding="utf-8")
            safe = "".join(c if c.isalnum() else "_" for c in image)
            (state / "running_image").write_text(f"sha256:id-{safe}\n", encoding="utf-8")

    return Host()


CREDENTIALS = f"octocat\n{TOKEN}\n"
OLD_IMAGE = "teleautomation-production-operations-api:release-" + OTHER_SHA
# Both files, secrets first and the release second, whatever the path style.
ENV_FILES = re.compile(r"--env-file \S*prod\.env --env-file \S*operations-release\.env ")


class TestItAcceptsOnlyAVerbAShaAndADigest:
    @pytest.mark.parametrize("sha", ["abc", SHA.upper(), SHA + "a", "g" * 40, ""])
    def test_a_malformed_sha_is_refused_before_anything_runs(self, host, sha):
        result = host.run("verify", sha, DIGEST, stdin=CREDENTIALS)
        assert result.returncode != 0
        assert host.calls() == ""

    @pytest.mark.parametrize("digest", ["c" * 64, "sha256:" + "c" * 63, "sha512:" + "c" * 64, "sha256:" + "C" * 64])
    def test_a_malformed_digest_is_refused_before_anything_runs(self, host, digest):
        result = host.run("deploy", SHA, digest, stdin=CREDENTIALS)
        assert result.returncode != 0
        assert host.calls() == ""

    @pytest.mark.parametrize("args", [("shell",), ("deploy", SHA), ("status", "extra"), ("verify", SHA, DIGEST, "x"), ()])
    def test_unknown_verbs_and_wrong_arity_are_refused(self, host, args):
        assert host.run(*args).returncode != 0
        assert "pull" not in host.calls()


class TestTheSshEntry:
    def test_the_request_is_split_into_words_and_never_evaluated(self, host):
        marker = host.path / "PWNED"
        result = host.run(
            stdin=CREDENTIALS, STUB_UID="1000",
            SSH_ORIGINAL_COMMAND=f"verify $(touch${{IFS}}{marker}) `id`",
        )
        assert result.returncode == 0, result.stderr
        assert not marker.exists()
        assert f"sudo -n {SCRIPT} verify $(touch${{IFS}}{marker}) `id`" in host.calls()

    def test_without_a_command_the_key_does_nothing(self, host):
        result = host.run(STUB_UID="1000")
        assert result.returncode != 0
        assert "sudo" not in host.calls()

    def test_more_than_three_words_are_refused(self, host):
        result = host.run(STUB_UID="1000", SSH_ORIGINAL_COMMAND=f"deploy {SHA} {DIGEST} ; id")
        assert result.returncode != 0
        assert "sudo" not in host.calls()


class TestVerify:
    def test_it_pulls_by_digest_through_a_throwaway_login_and_restarts_nothing(self, host):
        result = host.run("verify", SHA, DIGEST, stdin=CREDENTIALS)
        assert result.returncode == 0, result.stderr
        calls = host.calls()
        assert "login ghcr.io -u octocat --password-stdin" in calls
        assert f"pull --quiet {REF}" in calls
        assert " up " not in calls

    def test_the_registry_token_never_reaches_argv_logs_or_output(self, host):
        result = host.run("verify", SHA, DIGEST, stdin=CREDENTIALS)
        assert result.returncode == 0, result.stderr
        assert TOKEN not in host.calls()
        assert TOKEN not in result.stdout + result.stderr
        assert not (host.path / "deploy.log").exists() or TOKEN not in (host.path / "deploy.log").read_text()

    def test_an_image_built_from_another_commit_is_refused(self, host):
        result = host.run("verify", SHA, DIGEST, stdin=CREDENTIALS, STUB_LABEL_REVISION=OTHER_SHA)
        assert result.returncode != 0
        assert "revision label" in result.stderr

    def test_an_image_whose_baked_release_sha_differs_is_refused(self, host):
        result = host.run("verify", SHA, DIGEST, stdin=CREDENTIALS, STUB_BAKED_SHA=OTHER_SHA)
        assert result.returncode != 0
        assert "RELEASE_SHA" in result.stderr

    def test_missing_credentials_are_refused_before_any_registry_call(self, host):
        result = host.run("verify", SHA, DIGEST, stdin="")
        assert result.returncode != 0
        assert "login" not in host.calls()

    def test_a_host_compose_file_that_ignores_the_release_file_fails_verify(self, host):
        result = host.run("verify", SHA, DIGEST, stdin=CREDENTIALS, STUB_COMPOSE_READS_IMAGE="0")
        assert result.returncode != 0
        assert "OPERATIONS_IMAGE" in result.stderr


class TestDeploy:
    def test_it_needs_a_recorded_release_to_roll_back_to(self, host):
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS)
        assert result.returncode != 0
        assert "init" in result.stderr
        assert "pull" not in host.calls()

    def test_a_verified_release_is_recorded_by_digest_and_the_previous_is_kept(self, host):
        host.record(host.release, OLD_IMAGE, OTHER_SHA)
        host.serving(OTHER_SHA, OLD_IMAGE)
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS)
        assert result.returncode == 0, result.stderr
        assert f"OPERATIONS_IMAGE={REF}" in host.release.read_text()
        assert f"OPERATIONS_RELEASE_SHA={SHA}" in host.release.read_text()
        assert f"OPERATIONS_IMAGE={OLD_IMAGE}" in host.previous.read_text()
        up = [line for line in host.calls().splitlines() if " up " in line]
        assert len(up) == 1
        assert ENV_FILES.search(up[0]), up[0]
        assert "up -d --no-deps --no-build --pull never operations-api" in up[0]
        assert "is live" in result.stdout

    def test_a_release_that_fails_verification_is_rolled_back_and_reported(self, host):
        host.record(host.release, OLD_IMAGE, OTHER_SHA)
        host.serving(OTHER_SHA, OLD_IMAGE)
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS, STUB_BROKEN_SHA=SHA)
        assert result.returncode != 0
        assert "rolled back to bbbbbbb" in result.stderr
        assert f"OPERATIONS_IMAGE={OLD_IMAGE}" in host.release.read_text()
        assert len([line for line in host.calls().splitlines() if " up " in line]) == 2
        assert "failed-rolled-back" in (host.path / "deploy.log").read_text()

    def test_without_a_usable_previous_image_it_says_production_needs_attention(self, host):
        host.record(host.release, OLD_IMAGE, OTHER_SHA)
        host.serving(OTHER_SHA, OLD_IMAGE)
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS, STUB_BROKEN_SHA=SHA, STUB_MISSING_IMAGES=OLD_IMAGE)
        assert result.returncode != 0
        assert "needs attention" in result.stderr

    def test_redeploying_the_live_image_keeps_the_real_previous_release(self, host):
        host.record(host.release, REF, SHA, DIGEST)
        host.record(host.previous, OLD_IMAGE, OTHER_SHA)
        host.serving(SHA, REF)
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS)
        assert result.returncode == 0, result.stderr
        assert f"OPERATIONS_IMAGE={OLD_IMAGE}" in host.previous.read_text()

    def test_an_unhealthy_container_is_not_accepted(self, host):
        host.record(host.release, OLD_IMAGE, OTHER_SHA)
        host.serving(OTHER_SHA, OLD_IMAGE)
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS, STUB_HEALTH="unhealthy")
        assert result.returncode != 0
        assert "not healthy" in result.stderr

    def test_a_public_site_that_is_down_is_not_accepted(self, host):
        host.record(host.release, OLD_IMAGE, OTHER_SHA)
        host.serving(OTHER_SHA, OLD_IMAGE)
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS, STUB_PUBLIC_CODE="502")
        assert result.returncode != 0
        assert "public returned 502" in result.stderr

    def test_a_concurrent_host_build_blocks_the_deploy(self, host):
        host.record(host.release, OLD_IMAGE, OTHER_SHA)
        result = host.run("deploy", SHA, DIGEST, stdin=CREDENTIALS, STUB_PS="docker compose -p x build operations-api\n")
        assert result.returncode != 0
        assert "pull" not in host.calls()


class TestRollbackAndInit:
    def test_rollback_restores_the_previous_release_and_verifies_it(self, host):
        host.record(host.release, REF, SHA, DIGEST)
        host.record(host.previous, OLD_IMAGE, OTHER_SHA)
        host.serving(SHA, REF)
        result = host.run("rollback")
        assert result.returncode == 0, result.stderr
        assert f"OPERATIONS_IMAGE={OLD_IMAGE}" in host.release.read_text()
        assert f"OPERATIONS_IMAGE={REF}" in host.previous.read_text()
        assert "login" not in host.calls()

    def test_init_records_the_running_container_as_current_and_previous(self, host):
        host.serving(OTHER_SHA, "whatever")
        result = host.run("init", STUB_SERVED_SHA=OTHER_SHA)
        assert result.returncode == 0, result.stderr
        tag = f"teleautomation-production-operations-api:release-{OTHER_SHA}"
        assert f"OPERATIONS_IMAGE={tag}" in host.release.read_text()
        assert host.previous.read_text() == host.release.read_text()

    def test_init_refuses_while_the_host_compose_file_ignores_the_release_file(self, host):
        host.serving(OTHER_SHA, "whatever")
        result = host.run("init", STUB_COMPOSE_READS_IMAGE="0")
        assert result.returncode != 0
        assert "fix_and_deploy.sh" in result.stderr
        assert not host.release.exists()

    def test_status_warns_when_the_recorded_release_is_not_what_serves(self, host):
        host.record(host.release, REF, SHA, DIGEST)
        host.serving(OTHER_SHA, OLD_IMAGE)
        result = host.run("status")
        assert result.returncode != 0
        assert "WARNING" in result.stdout


class TestTheWrapperAndProvisioning:
    def test_the_compose_wrapper_always_passes_the_release_file_when_present(self, host):
        host.record(host.release, REF, SHA, DIGEST)
        env = {
            "PATH": f"{host.path / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "STUB_DIR": str(host.path),
            "TA_ENV_FILE": str(host.path / "prod.env"),
            "TA_RELEASE_DIR": str(host.path / "etc"),
            "TA_COMPOSE_DIR": str(host.path),
        }
        result = subprocess.run(["bash", str(WRAPPER), "ps"], text=True, capture_output=True, env=env, timeout=30)
        assert result.returncode == 0, result.stderr
        assert ENV_FILES.search(host.calls()), host.calls()

    def test_provisioning_refuses_anything_but_one_public_key_line(self, host):
        stubs = host.path / "bin"
        for tool in ("useradd", "passwd", "install", "visudo", "sshd", "mv"):
            _write(stubs / tool, f'#!/usr/bin/env bash\nprintf "{tool} %s\\n" "$*" >> "$STUB_DIR/docker.log"\nexit 1\n')
        env = {"PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "STUB_DIR": str(host.path)}
        private = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n"
        result = subprocess.run(["bash", str(PROVISION)], input=private, text=True, capture_output=True, env=env, timeout=30)
        assert result.returncode != 0
        assert "public key" in result.stderr
        assert "useradd" not in host.calls()

    def test_the_key_is_forced_to_the_deploy_script_and_restricted(self):
        text = PROVISION.read_text(encoding="utf-8")
        assert "command=\"%s\",restrict %s" in text
        assert "NOPASSWD: %s" in text and 'SCRIPT=/usr/local/sbin/teleautomation-deploy' in text
        assert "visudo -cf" in text
