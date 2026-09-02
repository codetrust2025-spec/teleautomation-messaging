"""An absent CI run must never be mistaken for a passing one.

`gh pr checks --watch` exits 0 when a pull request has no checks at all: it
prints "no checks reported" and returns success. fix_and_deploy.sh watches the
checks it has just caused to be created, so it can start watching before the
workflow has registered -- and then merge a commit whose CI never ran.

This was observed, not theorised: a watch one second after `pr create` returned
0 with no checks, and the run appeared seconds later.

These tests extract `await_checks` from the real script and run it against
stubbed `gh` output, so they exercise the guard rather than asserting that the
text of it exists.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fix_and_deploy.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to run the guard"
)


def await_checks_source() -> str:
    """The function as it is actually written in the deploy script."""
    body = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^await_checks\(\) \{.*?^\}", body, re.S | re.M)
    assert match, "await_checks is not defined in fix_and_deploy.sh"
    return match.group(0)


def run_guard(stub_output: str, stub_exit: int = 0, timeout_s: int = 0) -> subprocess.CompletedProcess:
    """Run await_checks with `gh` replaced by a stub printing stub_output."""
    harness = f"""
set -uo pipefail
CHECKS_APPEAR_TIMEOUT={timeout_s}
die() {{ printf 'FAILED: %s\\n' "$*" >&2; exit 1; }}
fake_gh() {{ printf '%s' '{stub_output}'; return {stub_exit}; }}
{await_checks_source()}
await_checks "test PR" fake_gh
echo GUARD_PASSED
"""
    return subprocess.run(["bash", "-c", harness], capture_output=True, text=True)


class TestAnAbsentRunIsNotAPass:
    def test_no_checks_reported_is_a_failure(self) -> None:
        """The exact string gh prints, and the exact case that made this
        necessary: gh returns success alongside it."""
        result = run_guard("no checks reported on the 'x' branch", stub_exit=0)
        assert result.returncode != 0
        assert "GUARD_PASSED" not in result.stdout
        assert "refusing to treat an absent run as a pass" in result.stderr

    def test_empty_output_is_a_failure(self) -> None:
        result = run_guard("", stub_exit=0)
        assert result.returncode != 0
        assert "GUARD_PASSED" not in result.stdout


class TestARealRunPassesThrough:
    def test_a_pending_check_is_enough_to_start_watching(self) -> None:
        """The guard only waits for checks to EXIST. Whether they pass is the
        watch's job, so a pending check must let it through rather than block
        until the timeout."""
        result = run_guard("verify\\tpending\\t0\\thttps://example/1")
        assert result.returncode == 0, result.stderr
        assert "GUARD_PASSED" in result.stdout

    def test_a_skipped_check_still_counts_as_registered(self) -> None:
        """A change-aware workflow skips the lane it did not select. Skipped
        jobs are still reported checks, so they must not look like an absent
        run."""
        result = run_guard("frontend\\tskipping\\t0\\thttps://example/2")
        assert result.returncode == 0, result.stderr
        assert "GUARD_PASSED" in result.stdout


class TestItIsWiredIntoBothPolls:
    @pytest.mark.parametrize("stage", ["run_ops_ci", "run_pin_ci"])
    def test_the_guard_runs_before_the_watch(self, stage: str) -> None:
        body = SCRIPT.read_text(encoding="utf-8")
        match = re.search(rf"^{stage}\(\) \{{.*?^\}}", body, re.S | re.M)
        assert match, f"{stage} is not defined"
        fn = match.group(0)
        assert "await_checks" in fn, f"{stage} watches checks without waiting for them to exist"
        assert fn.index("await_checks") < fn.index("--watch"), (
            f"{stage} calls await_checks after the watch, which is too late"
        )
