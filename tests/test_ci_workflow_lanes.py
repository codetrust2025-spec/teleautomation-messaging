"""The shape of Marketing CI that keeps the lanes safe and cheap.

A summary job used to run after every lane and fail if the lane that was chosen
had not run what it should. It cost a billed minute per run, and so did a
separate classifier job. Both are gone; what they guaranteed is pinned here
instead, and any change to the workflow takes the full lane, which runs this:

  - one job always runs, classifies, and fails on a lane it does not know;
  - each lane runs exactly the jobs it needs, and a heavy job cannot be skipped
    on a lane that needs it;
  - the pin checks run on both pin lanes and are the same checks verify runs;
  - the triggers and permissions are what the classifier relies on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
JOBS = WORKFLOW["jobs"]
LANES = ("pin", "pin-dual", "full")
NEEDS = {"pin": set(), "pin-dual": {"dual-service"}, "full": {"verify", "dual-service"}}


def runs_on_lane(expression: str | None, lane: str) -> bool:
    """Evaluate the only expression forms this workflow uses for a lane."""
    if expression is None:
        return True
    allowed = re.fullmatch(r"(needs\.ci\.outputs\.lane == '[a-z-]+'( \|\| )?)+", expression)
    assert allowed, f"unexpected job condition: {expression}"
    return any(match == lane for match in re.findall(r"== '([a-z-]+)'", expression))


def step(job: str, name: str) -> dict:
    return next(s for s in JOBS[job]["steps"] if s.get("name") == name)


def test_three_jobs_and_no_separate_classifier_or_summary_gate() -> None:
    assert set(JOBS) == {"ci", "verify", "dual-service"}


def test_the_ci_job_always_runs() -> None:
    assert "if" not in JOBS["ci"] and "needs" not in JOBS["ci"]


@pytest.mark.parametrize("lane", LANES)
def test_each_lane_runs_exactly_the_heavy_jobs_it_needs(lane: str) -> None:
    ran = {name for name in ("verify", "dual-service") if runs_on_lane(JOBS[name].get("if"), lane)}
    assert ran == NEEDS[lane]
    for name in ("verify", "dual-service"):
        assert JOBS[name]["needs"] == "ci"


def test_the_ci_job_fails_on_a_lane_it_does_not_know() -> None:
    check = step("ci", "The lane is one this workflow knows")
    assert "if" not in check
    assert check["env"]["LANE"] == "${{ steps.pick.outputs.lane }}"
    assert re.search(r"^\s*pin\|pin-dual\|full\) ", check["run"], re.M)
    assert re.search(r"\*\) .*exit 1", check["run"])


def test_the_lane_output_comes_from_the_classifier() -> None:
    pick = next(s for s in JOBS["ci"]["steps"] if s.get("id") == "pick")
    assert pick["run"].strip() == "bash scripts/ci_classify.sh"
    assert JOBS["ci"]["outputs"]["lane"] == "${{ steps.pick.outputs.lane }}"
    assert pick["env"]["BEFORE"] == "${{ github.event.before }}"
    assert pick["env"]["BASE"] == "${{ github.event.pull_request.base.sha }}"


def test_the_pin_checks_run_on_both_pin_lanes_and_only_there() -> None:
    pick_index = next(i for i, s in enumerate(JOBS["ci"]["steps"]) if s.get("id") == "pick")
    pin_steps = JOBS["ci"]["steps"][pick_index + 2:]
    assert pin_steps, "the pin checks are missing"
    for s in pin_steps:
        assert s.get("if") == "steps.pick.outputs.lane != 'full'", s
    commands = " ".join(s.get("run", "") for s in pin_steps)
    assert "docker compose -f docker-compose.production.yml config --quiet" in commands
    assert "tests/test_production_compose_contract.py" in commands


def test_the_pin_compose_check_is_the_one_verify_runs() -> None:
    name = "Validate authoritative production Compose"
    assert step("ci", name)["env"] == step("verify", name)["env"]
    assert step("ci", name)["run"] == step("verify", name)["run"]


def test_triggers_are_pull_requests_and_pushes_to_main() -> None:
    triggers = WORKFLOW.get("on", WORKFLOW.get(True))
    assert set(triggers) == {"push", "pull_request"}
    assert triggers["push"] == {"branches": ["main"]}


def test_only_the_classifier_may_read_check_runs_and_nothing_writes() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert JOBS["ci"]["permissions"] == {"contents": "read", "checks": "read"}
    assert "permissions" not in JOBS["verify"] and "permissions" not in JOBS["dual-service"]
