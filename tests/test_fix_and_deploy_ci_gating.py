"""Nothing merges or deploys unless both repositories' required checks passed.

test_deploy_waits_for_checks.py exercises the CI guard functions one at a time.
This file runs the script's real stage loop and its real `ops_ci` / `pin_ci`
stages, with every other stage replaced by a stub that only records that it
ran, against a fake `gh` whose answers change from one poll to the next. That
is the shape real CI has -- jobs register late, finish late, fail, get
cancelled -- and the question asked is the one that matters in production:
did any stage after CI (merge, sync, build, deploy, verify) run?

No network, no git, no host: the stubs touch nothing outside a temp directory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fix_and_deploy.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to run the pipeline"
)

STAGES = [
    "ops_pr", "pin", "ops_ci", "pin_ci",
    "ops_merge", "preflight", "pin_merge",
    "sync", "build", "deploy", "verify",
]
AFTER_CI = STAGES[STAGES.index("pin_ci") + 1:]


def source(pattern: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(pattern, text, re.S | re.M)
    assert match, f"{pattern!r} not found in fix_and_deploy.sh"
    return match.group(0)


def function(name: str) -> str:
    return source(rf"^{name}\(\) \{{.*?^\}}")


def rows(*checks: tuple[str, str]) -> str:
    """`gh pr checks` output without a terminal: tab-separated rows."""
    return "".join(f"{n}\t{s}\t1s\thttps://example/{i}\t\n" for i, (n, s) in enumerate(checks))


OPS_GREEN = rows(("classify", "pass"), ("python", "pass"), ("container", "pass"), ("ci", "pass"))
PIN_GREEN = rows(("ci", "pass"), ("verify", "skipping"), ("dual-service", "pass"))


def pipeline(tmp_path: Path, ops: list[str], pin: list[str]) -> subprocess.CompletedProcess:
    """Run the real stage loop. Each plain `gh pr checks` call of a repository
    returns that repository's next response (the last one repeats); a `--watch`
    behaves as gh's does: it fails if a check it can see failed or was
    cancelled, otherwise it waits for the current checks and returns 0."""
    for repo, responses in (("ops", ops), ("pin", pin)):
        for i, text in enumerate(responses):
            (tmp_path / f"{repo}{i}").write_text(text, encoding="utf-8", newline="")
    stubs = "\n".join(
        f'run_{s}() {{ echo "RAN {s}"; }}' for s in STAGES if s not in ("ops_ci", "pin_ci")
    )
    script = f"""
set -euo pipefail
dir='{tmp_path.as_posix()}'
OPERATIONS_BRANCH=fix/thing
OPERATIONS_SHA=0123456789012345678901234567890123456789
CHECKS_APPEAR_TIMEOUT=60
{source(r'^STAGES=\(.*?\)$')}
{source(r'^OPS_GATE_CHECK=.*?^PIN_OTHER_CHECKS=.*?$')}
say() {{ printf '  %s\\n' "$*"; }}
die() {{ printf '\\nFAILED: %s\\n' "$*" >&2; exit 1; }}
sleep() {{ :; }}
done_already() {{ return 1; }}
mark_done() {{ :; }}
branch_is_merged() {{ return 1; }}
require_pinned_head() {{ :; }}
current_anchor() {{ echo old; }}
pin_branch() {{ echo chore/pin-0123456; }}
fake() {{
  local repo="$1"; shift
  local n i last
  n="$(cat "$dir/$repo.n" 2>/dev/null || echo 0)"
  last=$(ls "$dir" | grep -c "^$repo[0-9]")
  i=$n; [ "$i" -lt "$last" ] || i=$((last - 1))
  case " $* " in
    *" --watch "*)
      echo "$repo" >> "$dir/watches"
      ! awk -F'\\t' '$2 == "fail" || $2 == "cancel" {{ f = 1 }} END {{ exit !f }}' "$dir/$repo$i"
      return ;;
  esac
  cat "$dir/$repo$i"
  echo $((n + 1)) > "$dir/$repo.n"
  awk -F'\\t' '$2 == "fail" || $2 == "cancel" {{ f = 1 }} END {{ exit f }}' "$dir/$repo$i"
}}
ops_gh() {{ fake ops "$@"; }}
gh() {{ fake pin "$@"; }}
{stubs}
{function("check_states")}
{function("await_checks")}
{function("watch_checks")}
{function("run_ops_ci")}
{function("run_pin_ci")}
{source(r'^for stage in "\$\{STAGES\[@\]\}"; do\n  if done_already.*?^done$')}
echo PIPELINE_COMPLETE
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def ran(result: subprocess.CompletedProcess) -> list[str]:
    return re.findall(r"^RAN (\w+)$", result.stdout, re.M)


def assert_stopped_before_merge(result: subprocess.CompletedProcess) -> None:
    assert result.returncode != 0, result.stdout
    assert "PIPELINE_COMPLETE" not in result.stdout
    assert not set(ran(result)) & set(AFTER_CI), f"ran after a failed CI: {ran(result)}"
    assert "FAILED:" in result.stderr


class TestGreenProceeds:
    def test_both_green_runs_every_stage(self, tmp_path: Path) -> None:
        result = pipeline(tmp_path, [OPS_GREEN], [PIN_GREEN])
        assert result.returncode == 0, result.stderr
        assert ran(result) == [s for s in STAGES if s not in ("ops_ci", "pin_ci")]
        assert "Operations CI green" in result.stdout and "pin CI green" in result.stdout

    def test_delayed_registration_then_green_proceeds(self, tmp_path: Path) -> None:
        """Nothing registered, then only the fast job, then the gate pending,
        then everything passed: the realistic slow start."""
        ops = [
            "no checks reported on the 'fix/thing' branch",
            rows(("classify", "pass")),
            rows(("classify", "pass"), ("python", "pending"), ("ci", "pending")),
            OPS_GREEN,
        ]
        pin = ["", rows(("ci", "pending")), rows(("ci", "pass"), ("verify", "skipping"), ("dual-service", "pending")), PIN_GREEN]
        result = pipeline(tmp_path, ops, pin)
        assert result.returncode == 0, result.stderr
        assert set(AFTER_CI) <= set(ran(result))


class TestPartialRunsStop:
    def test_operations_issue_479(self, tmp_path: Path) -> None:
        """Only `classify` ever registers and passes: the old script said
        green here. The gate never registers, so the wait times out."""
        result = pipeline(tmp_path, [rows(("classify", "pass"))], [PIN_GREEN])
        assert_stopped_before_merge(result)
        assert "has not registered ci" in result.stderr

    def test_pin_heavy_jobs_never_register(self, tmp_path: Path) -> None:
        result = pipeline(tmp_path, [OPS_GREEN], [rows(("ci", "pass"))])
        assert_stopped_before_merge(result)
        assert "has not registered verify dual-service" in result.stderr

    def test_no_checks_at_all(self, tmp_path: Path) -> None:
        result = pipeline(tmp_path, ["no checks reported on the 'fix/thing' branch"], [PIN_GREEN])
        assert_stopped_before_merge(result)

    def test_gate_vanishes_after_the_watch(self, tmp_path: Path) -> None:
        """Registered, watched, then not reported: absent is not pass."""
        ops = [rows(("classify", "pass"), ("ci", "pending")), rows(("classify", "pass"))]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert_stopped_before_merge(result)
        assert "required check ci is absent" in result.stderr


class TestFailuresStop:
    def test_gate_fails_after_registering_late(self, tmp_path: Path) -> None:
        """#479 as it actually ended: the gate registered late and failed."""
        ops = [
            rows(("classify", "pass")),
            rows(("classify", "pass"), ("ci", "pending")),
            rows(("classify", "pass"), ("python", "fail"), ("ci", "fail")),
        ]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert_stopped_before_merge(result)

    def test_side_job_fails_but_gate_passes(self, tmp_path: Path) -> None:
        ops = [rows(("ci", "pass"), ("image", "fail"))]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert_stopped_before_merge(result)

    def test_pin_fails_while_operations_is_green(self, tmp_path: Path) -> None:
        pin = [rows(("ci", "pass"), ("verify", "skipping"), ("dual-service", "fail"))]
        result = pipeline(tmp_path, [OPS_GREEN], pin)
        assert_stopped_before_merge(result)

    def test_gate_skipped(self, tmp_path: Path) -> None:
        result = pipeline(tmp_path, [rows(("classify", "pass"), ("ci", "skipping"))], [PIN_GREEN])
        assert_stopped_before_merge(result)
        assert "required check ci is skipping" in result.stderr


class TestCancellationsStop:
    def test_gate_cancelled(self, tmp_path: Path) -> None:
        ops = [rows(("classify", "pass"), ("ci", "pending")), rows(("classify", "pass"), ("ci", "cancel"))]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert_stopped_before_merge(result)

    def test_pin_lane_cancelled(self, tmp_path: Path) -> None:
        pin = [rows(("ci", "pass"), ("verify", "cancel"), ("dual-service", "pass"))]
        result = pipeline(tmp_path, [OPS_GREEN], pin)
        assert_stopped_before_merge(result)

    def test_one_of_two_gate_runs_cancelled(self, tmp_path: Path) -> None:
        """Conservative on purpose: a cancelled run of the gate is not a pass."""
        ops = [rows(("ci", "pass"), ("ci", "cancel"))]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert_stopped_before_merge(result)


class TestDelayedJobsAreWaitedFor:
    def test_job_still_pending_after_the_watch_is_watched_again(self, tmp_path: Path) -> None:
        """A job registered mid-watch is still pending when the watch returns;
        the verdict waits for it rather than declaring green."""
        ops = [
            rows(("ci", "pending")),
            rows(("ci", "pass"), ("image", "pending")),
            rows(("ci", "pass"), ("image", "pass")),
        ]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "watches").read_text().split().count("ops") == 2

    def test_job_that_never_finishes_stops_the_release(self, tmp_path: Path) -> None:
        ops = [rows(("ci", "pass"), ("image", "pending"))]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert_stopped_before_merge(result)
        assert "still has pending checks" in result.stderr

    def test_late_job_that_fails_stops_the_release(self, tmp_path: Path) -> None:
        ops = [rows(("ci", "pending")), rows(("ci", "pass"), ("image", "pending")), rows(("ci", "pass"), ("image", "fail"))]
        result = pipeline(tmp_path, ops, [PIN_GREEN])
        assert_stopped_before_merge(result)
