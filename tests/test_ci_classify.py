"""Which checks a Marketing CI run needs, driven through the real classifier.

scripts/ci_classify.sh decides the lane from git and, where it must, from the
GitHub API. These tests run it in throwaway repositories shaped like the real
thing -- a release anchor, its contract test, a pin commit, the merge
fix_and_deploy.sh makes -- with `gh` replaced by a stub that answers from files
and records every call.

The stub prints what the real `--jq` filters produce, so the filters themselves
are not exercised here; they were checked against the live API by replaying the
classifier over real September 2026 pins, merges and Marketing changes.

The rules that matter most are the fail-safe ones: a Marketing change that is
not exactly a pin is always `full`, an Operations range that cannot be read is
never `pin`, and a merged pin is only trusted when its pull request passed with
the same tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_classify.sh"
COMPOSE = "docker-compose.production.yml"
CONTRACT = "tests/test_production_compose_contract.py"
OLD = "1" * 40
NEW = "2" * 40

FRONTEND_RULE = "#!/usr/bin/env bash\ncat >/dev/null\necho frontend\n"
BACKEND_RULE = "#!/usr/bin/env bash\ncat >/dev/null\necho full\n"
PASSED = "ci completed success\ndual-service completed success\nverify completed skipped\n"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git are required to run the classifier",
)

STUB = r"""#!/usr/bin/env bash
# Stand-in for `gh api`: answers from files named by STUB_* variables.
printf '%s\n' "$*" >> "$STUB_LOG"
path="$2"
answer() {  # file exit-code
  [ "${2:-0}" = 0 ] || exit "$2"
  [ -f "$1" ] && cat "$1"
  exit 0
}
case "$path" in
  repos/*/compare/*)             answer "$STUB_COMPARE" "${STUB_COMPARE_EXIT:-0}" ;;
  repos/*/contents/scripts/ci_lane.sh*)
    [ "${STUB_RULE_EXIT:-0}" = 0 ] || exit "$STUB_RULE_EXIT"
    base64 < "$STUB_RULE" | tr -d '\n'; echo ;;
  repos/*/commits/*/check-runs*) answer "$STUB_CHECKS" "${STUB_CHECKS_EXIT:-0}" ;;
  *) echo "unexpected gh call: $*" >&2; exit 99 ;;
esac
"""


class Repo:
    """A Marketing-shaped repository with a stubbed `gh` on PATH."""

    def __init__(self, tmp: Path) -> None:
        self.path = tmp / "repo"
        self.path.mkdir()
        self.bin = tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "gh"
        stub.write_text(STUB, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        self.files = {name: tmp / f"stub-{name}" for name in ("compare", "rule", "checks", "log")}
        self.files["log"].write_text("", encoding="utf-8")
        self.stub_env: dict[str, str] = {}
        self.answer(compare="frontend-change.jsx\n", rule=BACKEND_RULE, checks=PASSED)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "ci@example.invalid")
        self.git("config", "user.name", "ci")
        self.write_pin(OLD)
        self.write("main.py", "print('marketing')\n")
        self.commit("base")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True,
                              check=True).stdout.strip()

    def write(self, name: str, content: str) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    def write_pin(self, sha: str) -> None:
        self.write(COMPOSE, f"x-release-shas:\n  operations: &operations-release {sha}\n")
        self.write(CONTRACT, f'OPERATIONS_RELEASE = "{sha}"\n')

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def answer(self, *, compare: str | None = None, rule: str | None = None,
               checks: str | None = None, **exits: int) -> None:
        for key, value in (("compare", compare), ("rule", rule), ("checks", checks)):
            if value is not None:
                self.files[key].write_text(value, encoding="utf-8", newline="\n")
        for key, value in exits.items():
            self.stub_env[f"STUB_{key.upper()}"] = str(value)

    def calls(self) -> list[str]:
        return [line for line in self.files["log"].read_text(encoding="utf-8").splitlines() if line]

    def classify(self, **env: str) -> tuple[str, str]:
        output = self.path.parent / "github-output"
        output.write_text("", encoding="utf-8")
        full_env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(self.files["log"]),
            "STUB_COMPARE": str(self.files["compare"]),
            "STUB_RULE": str(self.files["rule"]),
            "STUB_CHECKS": str(self.files["checks"]),
            "REPO": "owner/marketing",
            "REPO_TOKEN": "repo-token",
            "PEER": "owner/operations",
            "PEER_TOKEN": "peer-token",
            "GITHUB_OUTPUT": str(output),
            **self.stub_env,
            **env,
        }
        result = subprocess.run(["bash", str(SCRIPT)], cwd=self.path, env=full_env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        lane = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("lane="))
        assert output.read_text(encoding="utf-8").strip() == f"lane={lane}"
        return lane, result.stdout

    # ── shapes fix_and_deploy.sh and ordinary work produce ──────────────────
    def pin_branch(self, sha: str = NEW, extra: dict[str, str] | None = None) -> tuple[str, str]:
        base = self.git("rev-parse", "main")
        self.git("checkout", "-q", "-b", f"chore/pin-{sha[:7]}")
        self.write_pin(sha)
        for name, content in (extra or {}).items():
            self.write(name, content)
        head = self.commit(f"pin Operations to {sha[:7]}")
        return base, head

    def merge_to_main(self, branch_head: str) -> tuple[str, str]:
        self.git("checkout", "-q", "main")
        before = self.git("rev-parse", "HEAD")
        self.git("merge", "-q", "--no-ff", "-m", "Merge pull request #1", branch_head)
        return before, self.git("rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


class TestPullRequests:
    def test_a_marketing_change_takes_the_full_lane(self, repo: Repo) -> None:
        base = repo.git("rev-parse", "HEAD")
        repo.write("main.py", "print('changed')\n")
        repo.commit("marketing change")
        lane, _ = repo.classify(EVENT="pull_request", BASE=base)
        assert lane == "full"
        assert repo.calls() == []  # decided from git alone

    def test_a_pin_of_a_frontend_only_range_takes_the_pin_lane(self, repo: Repo) -> None:
        base, _ = repo.pin_branch()
        repo.answer(rule=FRONTEND_RULE)
        lane, out = repo.classify(EVENT="pull_request", BASE=base)
        assert lane == "pin"
        assert f"repos/owner/operations/compare/{OLD}...{NEW}" in "\n".join(repo.calls())
        assert f"ref={NEW}" in "\n".join(repo.calls())  # the rule as it exists at the new commit

    def test_a_pin_of_a_backend_range_skips_verify_but_keeps_dual_service(self, repo: Repo) -> None:
        base, _ = repo.pin_branch()
        lane, _ = repo.classify(EVENT="pull_request", BASE=base)
        assert lane == "pin-dual"

    def test_a_pin_carrying_a_marketing_file_is_not_a_pin(self, repo: Repo) -> None:
        base, _ = repo.pin_branch(extra={"main.py": "print('smuggled')\n"})
        repo.answer(rule=FRONTEND_RULE)
        assert repo.classify(EVENT="pull_request", BASE=base)[0] == "full"

    def test_a_pin_whose_anchor_did_not_move_is_not_trusted(self, repo: Repo) -> None:
        base, _ = repo.pin_branch(sha=OLD, extra={CONTRACT: f'OPERATIONS_RELEASE = "{OLD}"  # touched\n'})
        assert repo.classify(EVENT="pull_request", BASE=base)[0] == "full"

    def test_an_unreadable_anchor_is_not_trusted(self, repo: Repo) -> None:
        base = repo.git("rev-parse", "HEAD")
        repo.git("checkout", "-q", "-b", "chore/pin-broken")
        repo.write(COMPOSE, "x-release-shas:\n  operations: &operations-release not-a-sha\n")
        repo.write(CONTRACT, 'OPERATIONS_RELEASE = "not-a-sha"\n')
        repo.commit("broken pin")
        assert repo.classify(EVENT="pull_request", BASE=base)[0] == "full"

    def test_no_base_is_full(self, repo: Repo) -> None:
        assert repo.classify(EVENT="pull_request", BASE="")[0] == "full"

    @pytest.mark.parametrize(
        "setup,why",
        [
            ({"PEER_TOKEN": ""}, "no token to read Operations"),
            ({"compare_exit": 1}, "the compare request failed"),
            ({"rule_exit": 1}, "the lane rule could not be fetched"),
        ],
    )
    def test_an_operations_range_that_cannot_be_read_is_never_the_pin_lane(
        self, repo: Repo, setup: dict, why: str
    ) -> None:
        base, _ = repo.pin_branch()
        repo.answer(rule=FRONTEND_RULE, **{k: v for k, v in setup.items() if k != "PEER_TOKEN"})
        env = {"PEER_TOKEN": setup["PEER_TOKEN"]} if "PEER_TOKEN" in setup else {}
        assert repo.classify(EVENT="pull_request", BASE=base, **env)[0] == "pin-dual", why

    def test_an_empty_operations_range_is_not_frontend(self, repo: Repo) -> None:
        base, _ = repo.pin_branch()
        repo.answer(compare="", rule=FRONTEND_RULE)
        assert repo.classify(EVENT="pull_request", BASE=base)[0] == "pin-dual"


class TestPushesToMain:
    def test_the_merge_of_a_pin_that_passed_gets_only_the_pin_checks(self, repo: Repo) -> None:
        _, head = repo.pin_branch()
        before, _ = repo.merge_to_main(head)
        lane, out = repo.classify(EVENT="push", BEFORE=before)
        assert lane == "pin"
        calls = "\n".join(repo.calls())
        assert f"repos/owner/marketing/commits/{head}/check-runs" in calls
        assert "compare" not in calls  # the pull request already covered the range

    @pytest.mark.parametrize(
        "checks,why",
        [
            ("ci completed failure\ndual-service completed success\nverify completed success\n",
             "ci never passed -- the job did not run, or failed"),
            ("ci completed success\ndual-service completed failure\nverify completed skipped\n",
             "the cross-service check failed"),
            ("ci completed success\ndual-service in_progress null\nverify completed skipped\n",
             "a check is still running"),
            ("ci completed success\ndual-service completed cancelled\nverify completed skipped\n",
             "a check was cancelled"),
            ("ci completed success\nverify completed skipped\n", "dual-service is missing"),
            ("", "no checks at all"),
        ],
    )
    def test_a_pin_merged_without_passing_gets_the_checks_its_range_needs(
        self, repo: Repo, checks: str, why: str
    ) -> None:
        _, head = repo.pin_branch()
        before, _ = repo.merge_to_main(head)
        repo.answer(checks=checks)
        assert repo.classify(EVENT="push", BEFORE=before)[0] == "pin-dual", why

    def test_an_unreadable_check_list_is_not_a_pass(self, repo: Repo) -> None:
        _, head = repo.pin_branch()
        before, _ = repo.merge_to_main(head)
        repo.answer(checks_exit=1)
        assert repo.classify(EVENT="push", BEFORE=before)[0] == "pin-dual"

    def test_no_token_for_the_check_list_is_not_a_pass(self, repo: Repo) -> None:
        _, head = repo.pin_branch()
        before, _ = repo.merge_to_main(head)
        assert repo.classify(EVENT="push", BEFORE=before, REPO_TOKEN="")[0] == "pin-dual"

    def test_a_push_carrying_a_marketing_commit_with_the_pin_is_full(self, repo: Repo) -> None:
        base, head = repo.pin_branch()
        repo.git("checkout", "-q", "main")
        repo.write("README.md", "moved on\n")
        repo.commit("a Marketing commit pushed together with the merge")
        repo.merge_to_main(head)
        # One push, two commits: measured from before both, it is not a pin.
        lane, _ = repo.classify(EVENT="push", BEFORE=base)
        assert lane == "full"
        assert not any("check-runs" in call for call in repo.calls())

    def test_a_pin_rebased_onto_a_moved_main_needs_its_range_checks(self, repo: Repo) -> None:
        base, head = repo.pin_branch()
        repo.git("checkout", "-q", "main")
        repo.write_pin(OLD)
        repo.write("README.md", "moved on\n")
        moved = repo.commit("main moves")
        # Merged with main at `moved`, whose diff to the merge is only the pin,
        # but whose pull request head was built on the older main.
        before, _ = repo.merge_to_main(head)
        assert before == moved and repo.git("rev-parse", f"{head}^") == base
        lane, _ = repo.classify(EVENT="push", BEFORE=before)
        assert lane == "pin-dual"
        assert not any("check-runs" in call for call in repo.calls())

    def test_a_pin_pushed_straight_to_main_is_checked_by_its_range(self, repo: Repo) -> None:
        before = repo.git("rev-parse", "HEAD")
        repo.write_pin(NEW)
        repo.commit("pin without a pull request")
        repo.answer(rule=FRONTEND_RULE)
        assert repo.classify(EVENT="push", BEFORE=before)[0] == "pin"
        repo.answer(rule=BACKEND_RULE)
        assert repo.classify(EVENT="push", BEFORE=before)[0] == "pin-dual"

    def test_a_marketing_change_pushed_to_main_is_full(self, repo: Repo) -> None:
        before = repo.git("rev-parse", "HEAD")
        repo.git("checkout", "-q", "-b", "feature")
        repo.write("main.py", "print('feature')\n")
        head = repo.commit("feature")
        repo.merge_to_main(head)
        assert repo.classify(EVENT="push", BEFORE=before)[0] == "full"

    @pytest.mark.parametrize("before", ["0" * 40, "", "3" * 40])
    def test_no_usable_previous_commit_is_full(self, repo: Repo, before: str) -> None:
        _, head = repo.pin_branch()
        repo.merge_to_main(head)
        assert repo.classify(EVENT="push", BEFORE=before)[0] == "full"


class TestEverythingElse:
    @pytest.mark.parametrize("event", ["workflow_dispatch", "schedule", ""])
    def test_any_other_event_is_full(self, repo: Repo, event: str) -> None:
        assert repo.classify(EVENT=event)[0] == "full"

    def test_every_lane_it_can_decide_is_one_the_workflow_handles(self) -> None:
        import re

        decided = set(re.findall(r"decide (pin-dual|pin|full)\b", SCRIPT.read_text(encoding="utf-8")))
        assert decided == {"pin", "pin-dual", "full"}
