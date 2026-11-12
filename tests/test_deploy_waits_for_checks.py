"""An absent or unfinished CI run must never be mistaken for a passing one.

`gh pr checks --watch` exits 0 when a pull request has no checks at all: it
prints "no checks reported" and returns success. fix_and_deploy.sh watches the
checks it has just caused to be created, so it can start watching before the
workflow has registered -- and then merge a commit whose CI never ran.

This was observed, not theorised: a watch one second after `pr create` returned
0 with no checks, and the run appeared seconds later.

Waiting for *any* check was not enough either. On 12 Nov 2026 (Operations
#479) only the four-second `classify` job had registered; the watch followed it
alone, the script printed "Operations CI green", and the required `ci` gate --
which then failed -- had not registered yet. So the script waits for the named
gate, and decides green from the checks re-read after the watch, not from the
watch's exit code.

These tests extract the functions from the real script and run them against
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


def function_source(name: str) -> str:
    """A function as it is actually written in the deploy script."""
    body = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{.*?^\}}", body, re.S | re.M)
    assert match, f"{name} is not defined in fix_and_deploy.sh"
    return match.group(0)


def rows(*checks: tuple[str, str]) -> str:
    """`gh pr checks` output without a terminal: tab-separated rows."""
    return "".join(
        f"{name}\t{state}\t1s\thttps://example/{i}\t\n" for i, (name, state) in enumerate(checks)
    )


def run(tmp_path: Path, responses: list[str], call: str) -> subprocess.CompletedProcess:
    """Run `call` with `gh` replaced by a fake.

    Successive plain calls print successive `responses` (the last repeats);
    `--watch` calls succeed silently and are counted. The fake keeps its state
    in files because the script calls it inside command substitutions, which
    are subshells whose variables do not survive the call.
    """
    for i, text in enumerate(responses):
        (tmp_path / f"r{i}").write_text(text, encoding="utf-8", newline="")
    script = f"""
set -uo pipefail
CHECKS_APPEAR_TIMEOUT=0
sleep() {{ :; }}
die() {{ printf 'FAILED: %s\\n' "$*" >&2; exit 1; }}
dir='{tmp_path.as_posix()}'
fake_gh() {{
  case " $* " in *" --watch "*) echo watch >> "$dir/watches"; return 0 ;; esac
  local n i
  n="$(cat "$dir/n" 2>/dev/null || echo 0)"
  i=$n; [ -e "$dir/r$i" ] || i={len(responses) - 1}
  cat "$dir/r$i"
  echo $((n + 1)) > "$dir/n"
}}
{function_source("check_states")}
{function_source("await_checks")}
{function_source("watch_checks")}
{call}
echo VERDICT_GREEN
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def await_only(tmp_path: Path, output: str, required: str = "ci") -> subprocess.CompletedProcess:
    return run(tmp_path, [output], f'await_checks "test PR" "{required}" fake_gh')


def watch_only(
    tmp_path: Path, responses: list[str], gate: str = "ci", others: str = ""
) -> subprocess.CompletedProcess:
    return run(tmp_path, responses, f'watch_checks "test CI" "{gate}" "{others}" fake_gh')


class TestAnAbsentRunIsNotAPass:
    def test_no_checks_reported_is_a_failure(self, tmp_path: Path) -> None:
        """The exact string gh prints, and the exact case that made this
        necessary: gh returns success alongside it."""
        result = await_only(tmp_path, "no checks reported on the 'x' branch")
        assert result.returncode != 0
        assert "VERDICT_GREEN" not in result.stdout
        assert "refusing to treat an absent run as a pass" in result.stderr

    def test_empty_output_is_a_failure(self, tmp_path: Path) -> None:
        result = await_only(tmp_path, "")
        assert result.returncode != 0
        assert "VERDICT_GREEN" not in result.stdout


class TestTheGateMustRegister:
    def test_a_fast_job_alone_is_not_the_run(self, tmp_path: Path) -> None:
        """Operations #479: only `classify` existed when the watch began."""
        result = await_only(tmp_path, rows(("classify", "pass")))
        assert result.returncode != 0
        assert "has not registered ci" in result.stderr

    def test_a_name_that_merely_contains_the_gate_does_not_count(self, tmp_path: Path) -> None:
        result = await_only(tmp_path, rows(("ci-lint", "pass"), ("classify", "pass")))
        assert result.returncode != 0

    def test_every_required_check_must_register(self, tmp_path: Path) -> None:
        """Marketing's `ci` runs first; its heavy jobs register only after it."""
        result = await_only(tmp_path, rows(("ci", "pass")), required="ci verify dual-service")
        assert result.returncode != 0
        assert "verify dual-service" in result.stderr

    def test_a_pending_gate_is_enough_to_start_watching(self, tmp_path: Path) -> None:
        """The guard only waits for checks to EXIST; whether they pass is the
        verdict's job, so a pending gate must not block until the timeout."""
        result = await_only(tmp_path, rows(("classify", "pass"), ("ci", "pending")))
        assert result.returncode == 0, result.stderr

    def test_a_skipped_check_still_counts_as_registered(self, tmp_path: Path) -> None:
        """A change-aware workflow skips the lane it did not select. Skipped
        jobs are still reported checks, so they must not look like an absent
        run."""
        result = await_only(
            tmp_path,
            rows(("ci", "pass"), ("verify", "skipping"), ("dual-service", "pending")),
            required="ci verify dual-service",
        )
        assert result.returncode == 0, result.stderr


class TestTheVerdictComesFromTheChecks:
    def test_gate_passing_is_green(self, tmp_path: Path) -> None:
        result = watch_only(tmp_path, [rows(("classify", "pass"), ("python", "pass"), ("ci", "pass"))])
        assert result.returncode == 0, result.stderr
        assert "VERDICT_GREEN" in result.stdout

    def test_watch_exit_zero_with_a_failed_gate_is_not_green(self, tmp_path: Path) -> None:
        """The watch's 0 is not the verdict: re-read, the gate had failed."""
        result = watch_only(tmp_path, [rows(("classify", "pass"), ("ci", "fail"))])
        assert result.returncode != 0
        assert "required check ci is fail" in result.stderr

    def test_an_absent_gate_after_the_watch_is_not_green(self, tmp_path: Path) -> None:
        result = watch_only(tmp_path, [rows(("classify", "pass"))])
        assert result.returncode != 0
        assert "required check ci is absent" in result.stderr

    def test_a_skipped_gate_is_not_green(self, tmp_path: Path) -> None:
        result = watch_only(tmp_path, [rows(("ci", "skipping"))])
        assert result.returncode != 0

    def test_every_run_of_the_gate_must_pass(self, tmp_path: Path) -> None:
        """Two runs can cover one commit; one failing gate is a failure."""
        result = watch_only(tmp_path, [rows(("ci", "pass"), ("ci", "fail"))])
        assert result.returncode != 0

    def test_checks_registered_during_the_watch_are_watched_too(self, tmp_path: Path) -> None:
        """A job that registered after the watch started can still be pending
        when the watch returns: it is watched again, and then judged."""
        result = watch_only(
            tmp_path,
            [rows(("classify", "pass"), ("ci", "pending")), rows(("classify", "pass"), ("ci", "fail"))],
        )
        assert result.returncode != 0
        assert "required check ci is fail" in result.stderr
        assert (tmp_path / "watches").read_text().count("watch") == 2

    def test_a_failing_side_check_is_not_green(self, tmp_path: Path) -> None:
        result = watch_only(tmp_path, [rows(("ci", "pass"), ("image", "fail"))])
        assert result.returncode != 0

    def test_pin_lanes_may_be_skipped(self, tmp_path: Path) -> None:
        result = watch_only(
            tmp_path,
            [rows(("ci", "pass"), ("verify", "skipping"), ("dual-service", "pass"))],
            others="verify dual-service",
        )
        assert result.returncode == 0, result.stderr

    def test_pin_lanes_may_not_vanish(self, tmp_path: Path) -> None:
        result = watch_only(
            tmp_path, [rows(("ci", "pass"), ("verify", "skipping"))], others="verify dual-service"
        )
        assert result.returncode != 0
        assert "required check dual-service is absent" in result.stderr


class TestItIsWiredIntoBothPolls:
    @pytest.mark.parametrize("stage", ["run_ops_ci", "run_pin_ci"])
    def test_the_guard_runs_before_the_verdict(self, stage: str) -> None:
        fn = function_source(stage)
        assert "await_checks" in fn, f"{stage} watches checks without waiting for them to exist"
        assert "watch_checks" in fn, f"{stage} trusts the watch's exit code"
        assert fn.index("await_checks") < fn.index("watch_checks"), (
            f"{stage} calls await_checks after the watch, which is too late"
        )
        assert "--watch" not in fn, f"{stage} watches directly instead of through watch_checks"

    def test_operations_gate_is_its_protected_check(self) -> None:
        """Branch protection on Operations main requires the `ci` check."""
        text = SCRIPT.read_text(encoding="utf-8")
        assert re.search(r'^OPS_GATE_CHECK="\$\{OPS_GATE_CHECK:-ci\}"$', text, re.M)

    def test_pin_waits_for_the_jobs_behind_its_first_job(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        assert re.search(r'^PIN_GATE_CHECK="\$\{PIN_GATE_CHECK:-ci\}"$', text, re.M)
        assert re.search(r'^PIN_OTHER_CHECKS="\$\{PIN_OTHER_CHECKS:-verify dual-service\}"$', text, re.M)
