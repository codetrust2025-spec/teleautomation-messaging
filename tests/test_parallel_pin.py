"""The pin runs beside Operations CI without ever shipping untested code.

fix_and_deploy.sh opens the Marketing pin straight after the Operations pull
request, so the two repositories' CI run at the same time instead of one after
the other. That is only safe if the commit Marketing pins is the commit CI
tested and the commit that lands on Operations main. These tests drive the
real functions from the script, against throwaway git repositories standing in
for GitHub, and hold the four ways that could go wrong:

  * main is fast-forwarded to the pinned commit, never forced;
  * when main has moved, the PR is merged normally and the pin follows the
    merge commit, so nothing that reached main in the meantime is reverted;
  * a branch that moved after it was pinned stops the run;
  * the pin is never merged unless its commit is on Operations main.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fix_and_deploy.sh"
BRANCH = "feat/x"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git are required to run the pipeline functions",
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "ci", "GIT_AUTHOR_EMAIL": "ci@example.invalid",
    "GIT_COMMITTER_NAME": "ci", "GIT_COMMITTER_EMAIL": "ci@example.invalid",
}


def source(name: str) -> str:
    """A function exactly as fix_and_deploy.sh writes it."""
    match = re.search(rf"^{name}\(\) \{{.*?^\}}", SCRIPT.read_text(encoding="utf-8"), re.S | re.M)
    assert match, f"{name} is not defined in fix_and_deploy.sh"
    return match.group(0)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class Operations:
    """A bare 'GitHub' repository, the pipeline's clone, and a colleague's clone."""

    def __init__(self, tmp: Path) -> None:
        self.origin = tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.clone = tmp / "ops"
        self.other = tmp / "other"
        for path in (self.clone, self.other):
            subprocess.run(["git", "clone", "-q", str(self.origin), str(path)], check=True,
                           env={**os.environ, **GIT_ENV})
        self.commit(self.other, "base.txt", "main")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        git(self.clone, "fetch", "-q", "origin")
        git(self.clone, "checkout", "-q", "-b", BRANCH, "origin/main")
        self.head = self.commit(self.clone, "change.txt", BRANCH)
        git(self.clone, "push", "-q", "origin", f"HEAD:{BRANCH}")
        self.merge_file = tmp / "merge-commit"
        self.log = tmp / "log"
        self.log.write_text("", encoding="utf-8")
        self.tmp = tmp

    def commit(self, repo: Path, name: str, text: str) -> str:
        (repo / name).write_text(text, encoding="utf-8")
        git(repo, "add", name)
        git(repo, "commit", "-q", "-m", name)
        return git(repo, "rev-parse", "HEAD")

    def main_moves(self) -> str:
        """Someone else lands work on main while the PR is in CI."""
        git(self.other, "pull", "-q", "origin", "main")
        moved = self.commit(self.other, "colleague.txt", "theirs")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        return moved

    def origin_main(self) -> str:
        return git(self.clone, "ls-remote", str(self.origin), "refs/heads/main").split()[0]

    def run(self, body: str, *, pr_head: str | None = None) -> subprocess.CompletedProcess:
        """Run pipeline functions with `gh` answered by the repositories above."""
        harness = f"""
set -uo pipefail
OPS_REPO='{self.clone.as_posix()}'
OPERATIONS_BRANCH='{BRANCH}'
OPERATIONS_SHA='{self.head}'
SHA_FILE='{(self.tmp / "sha").as_posix()}'
LOG='{self.log.as_posix()}'
MERGE_FILE='{self.merge_file.as_posix()}'
say() {{ printf '  %s\\n' "$*"; }}
die() {{ printf 'FAILED: %s\\n' "$*" >&2; exit 1; }}
sleep() {{ :; }}
pin_branch() {{ echo "chore/pin-${{OPERATIONS_SHA:0:7}}"; }}
run_pin() {{ echo "run_pin $OPERATIONS_SHA" >> "$LOG"; }}
run_pin_ci() {{ echo "run_pin_ci $OPERATIONS_SHA" >> "$LOG"; }}
gh() {{ echo "gh $*" >> "$LOG"; }}
# Operations' GitHub, answered from the bare repository.
ops_gh() {{
  case "$*" in
    *"--json mergeStateStatus"*) echo CLEAN ;;
    *"--json headRefOid"*) echo '{pr_head or self.head}' ;;
    *"--json state"*)
      git -C "$OPS_REPO" fetch -q origin main
      if git -C "$OPS_REPO" merge-base --is-ancestor '{self.head}' origin/main; then echo MERGED; else echo OPEN; fi ;;
    *"--json mergeCommit"*) cat "$MERGE_FILE" 2>/dev/null ;;
    "pr merge "*)
      echo "ops_gh $*" >> "$LOG"
      scratch=$(mktemp -d)
      git clone -q '{self.origin.as_posix()}' "$scratch" \\
        && git -C "$scratch" merge -q --no-ff -m "Merge pull request" "origin/{BRANCH}" \\
        && git -C "$scratch" push -q origin HEAD:main \\
        && git -C "$scratch" rev-parse HEAD > "$MERGE_FILE" ;;
    *) echo "unexpected ops_gh call: $*" >&2; exit 99 ;;
  esac
}}
{source("branch_is_merged")}
{source("require_pinned_head")}
{source("await_merged")}
{source("run_ops_merge")}
{body}
"""
        return subprocess.run(["bash", "-c", harness], capture_output=True, text=True,
                              env={**os.environ, **GIT_ENV})


@pytest.fixture()
def ops(tmp_path: Path) -> Operations:
    return Operations(tmp_path)


class TestTheFastForward:
    def test_main_becomes_exactly_the_pinned_commit(self, ops: Operations) -> None:
        result = ops.run('run_ops_merge; echo "SHIPPED $OPERATIONS_SHA"')
        assert result.returncode == 0, result.stderr
        assert ops.origin_main() == ops.head
        assert f"SHIPPED {ops.head}" in result.stdout
        # The pin already names this commit: nothing is re-pinned, nothing merged by button.
        assert "run_pin" not in ops.log.read_text(encoding="utf-8")
        assert "pr merge" not in ops.log.read_text(encoding="utf-8")

    def test_the_branch_is_deleted_only_once_merged(self, ops: Operations) -> None:
        assert ops.run("run_ops_merge").returncode == 0
        branches = git(ops.clone, "ls-remote", "--heads", str(ops.origin))
        assert f"refs/heads/{BRANCH}" not in branches

    def test_it_is_never_forced(self) -> None:
        body = source("run_ops_merge")
        assert "--force" not in body and "-f " not in body
        assert re.search(r'push --quiet origin "\$OPERATIONS_SHA:refs/heads/main"', body)
        assert "+$OPERATIONS_SHA" not in body


class TestWhenMainHasMoved:
    def test_it_merges_normally_and_pins_the_merge_commit(self, ops: Operations) -> None:
        theirs = ops.main_moves()
        result = ops.run('run_ops_merge; echo "SHIPPED $OPERATIONS_SHA"')
        assert result.returncode == 0, result.stderr
        merged = ops.merge_file.read_text(encoding="utf-8").strip()
        assert ops.origin_main() == merged
        git(ops.clone, "fetch", "-q", "origin")
        # Both the branch and the colleague's work are in what ships.
        assert git(ops.clone, "merge-base", "--is-ancestor", ops.head, merged) == ""
        assert git(ops.clone, "merge-base", "--is-ancestor", theirs, merged) == ""
        assert f"SHIPPED {merged}" in result.stdout
        log = ops.log.read_text(encoding="utf-8")
        assert f"run_pin {merged}" in log and f"run_pin_ci {merged}" in log
        # The pin of the bare head would have shipped without the colleague's
        # commit, so it is closed rather than left to be merged.
        assert f"gh pr close chore/pin-{ops.head[:7]}" in log

    def test_the_recorded_commit_follows_the_merge(self, ops: Operations) -> None:
        ops.main_moves()
        assert ops.run("run_ops_merge").returncode == 0
        merged = ops.merge_file.read_text(encoding="utf-8").strip()
        assert (ops.tmp / "sha").read_text(encoding="utf-8") == merged


class TestAMovedBranchIsNotShipped:
    def test_a_push_after_the_pin_stops_the_run(self, ops: Operations) -> None:
        result = ops.run("run_ops_merge", pr_head="d" * 40)
        assert result.returncode != 0
        assert "moved" in result.stderr and "--restart" in result.stderr
        assert ops.origin_main() != ops.head  # nothing landed


class TestThePinWaitsForOperationsMain:
    def pin_merge(self, ops: Operations) -> subprocess.CompletedProcess:
        marketing = ops.tmp / "marketing.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(marketing)], check=True)
        here = ops.tmp / "marketing"
        subprocess.run(["git", "clone", "-q", str(marketing), str(here)], check=True,
                       env={**os.environ, **GIT_ENV})
        ops.commit(here, "compose.yml", "anchor")
        git(here, "push", "-q", "origin", "HEAD:main")
        body = f"""
HERE='{here.as_posix()}'
current_anchor() {{ echo old; }}
{source("run_pin_merge")}
run_pin_merge
"""
        return ops.run(body)

    def test_a_pin_of_an_unmerged_commit_is_refused(self, ops: Operations) -> None:
        result = self.pin_merge(ops)
        assert result.returncode != 0
        assert "not on Operations main" in result.stderr
        assert "gh pr merge" not in ops.log.read_text(encoding="utf-8")

    def test_once_merged_the_pin_goes_ahead(self, ops: Operations) -> None:
        assert ops.run("run_ops_merge").returncode == 0
        self.pin_merge(ops)
        assert "gh pr merge chore/pin-" in ops.log.read_text(encoding="utf-8")


class TestTheOrderGatesEveryMerge:
    def stages(self) -> list[str]:
        match = re.search(r"^STAGES=\(([^)]*)\)", SCRIPT.read_text(encoding="utf-8"), re.M)
        return match.group(1).split()

    def test_both_ci_runs_finish_before_anything_merges(self) -> None:
        order = self.stages()
        for gate in ("ops_ci", "pin_ci"):
            for merge in ("ops_merge", "pin_merge"):
                assert order.index(gate) < order.index(merge), (gate, merge)

    def test_the_pin_opens_before_operations_ci_is_awaited(self) -> None:
        order = self.stages()
        assert order.index("pin") < order.index("ops_ci")

    def test_operations_lands_before_the_pin(self) -> None:
        order = self.stages()
        assert order.index("ops_merge") < order.index("preflight") < order.index("pin_merge")

    def test_ci_checks_the_pinned_head(self) -> None:
        assert "require_pinned_head" in source("run_ops_ci")
        assert "require_pinned_head" in source("run_ops_merge")
