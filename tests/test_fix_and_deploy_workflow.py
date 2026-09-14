"""The break-glass release is written down once and automated once.

Normal releases merge to Operations main and its deploy workflow releases
production. ``scripts/fix_and_deploy.sh`` is the path for when that cannot run,
and a path used rarely is exactly the one that rots: these tests hold it to the
same guarantees as a CI release, and hold ``CLAUDE.md`` to describing it.

Two descriptions of one procedure drift, so the stage list in the script and
the stage list in the instructions must be the same list.

They also hold the line the READMEs take about environment specifics. Neither
repository names a host, an IP or a key path; those arrive through the
environment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "fix_and_deploy.sh"
INSTRUCTIONS = ROOT / "CLAUDE.md"

STAGES = ["preflight", "sync", "build", "release"]


def script() -> str:
    assert SCRIPT.exists(), "the break-glass release has no script"
    return SCRIPT.read_text(encoding="utf-8")


def instructions() -> str:
    assert INSTRUCTIONS.exists(), "the deploy rule has no written home"
    return INSTRUCTIONS.read_text(encoding="utf-8")


def function_body(name: str) -> str:
    body = script()
    start = body.index(f"{name}() {{")
    end = body.index("\n}\n", start)
    return body[start:end]


def flowed() -> str:
    """The instructions with markdown emphasis and line wrapping removed."""
    return re.sub(r"\s+", " ", instructions().replace("*", "").replace('"', "").replace("`", "")).lower()


class TestStages:
    def test_the_script_declares_every_stage_in_order(self):
        match = re.search(r"^STAGES=\(([^)]*)\)", script(), re.M)
        assert match, "no STAGES declaration to check"
        assert match.group(1).split() == STAGES

    def test_the_instructions_list_the_same_stages_in_the_same_order(self):
        blocks = re.findall(r"```[a-z]*\r?\n(.*?)\r?\n```", instructions(), re.S)
        listed = [b.split() for b in blocks if set(STAGES) <= set(b.split())]
        assert listed, "CLAUDE.md has no block listing every break-glass stage"
        assert listed[0] == STAGES, "the stage block does not match the script"

    def test_every_stage_has_an_implementation(self):
        for stage in STAGES:
            assert f"run_{stage}() {{" in script(), f"stage {stage} has no run_{stage}"

    def test_the_run_loop_walks_the_declared_stages(self):
        assert re.search(r'for stage in "\$\{STAGES\[@\]\}"', script())

    def test_progress_is_recorded_so_an_interrupted_run_resumes(self):
        body = script()
        assert "done_already" in body and "mark_done" in body


class TestItIsTheSameReleaseAsCI:
    def test_it_is_labelled_break_glass_and_points_at_the_normal_path(self):
        header = script()[:1200]
        assert "Break-glass" in header
        assert "Merging to Operations main" in header
        assert "releases production" in header

    def test_only_a_commit_on_operations_main_is_released(self):
        preflight = function_body("run_preflight")
        assert 'merge-base --is-ancestor "$OPERATIONS_SHA" origin/main' in preflight

    def test_the_host_must_already_record_releases(self):
        preflight = function_body("run_preflight")
        assert "$RELEASE_FILE" in preflight and "setup_ci_deploy.sh" in preflight

    def test_the_checkout_must_equal_the_commit_before_any_build(self):
        sync = function_body("run_sync")
        assert '[ "$HEAD" = "$OPS_SHA" ]' in sync

    def test_it_refuses_to_deploy_over_a_running_deploy(self):
        assert "another deploy is already running" in function_body("run_sync")

    def test_the_image_is_stamped_with_the_commit_and_tagged_for_release(self):
        build = function_body("run_build")
        assert 'OPERATIONS_BUILD_SHA="$SHA" docker compose -p "$PROJECT" --env-file "$ENV_FILE"' in build
        assert 'docker tag "$IMAGE" "$IMAGE:release-$SHA"' in build

    def test_the_build_never_reads_the_release_file(self):
        """With the release file, compose would resolve the registry image and
        the build would try to tag a digest reference."""
        build = function_body("run_build")
        assert "operations-release.env" not in build and "RELEASE_FILE" not in build

    def test_the_release_goes_through_teleautomation_deploy(self):
        release = function_body("run_release")
        assert '"$DEPLOY_SCRIPT deploy-local $OPERATIONS_SHA"' in release

    def test_build_and_release_skip_when_production_already_serves_it(self):
        assert "already_live" in function_body("run_build")
        assert "already_live" in function_body("run_release")
        check = function_body("already_live")
        assert "/version" in check and "OPERATIONS_RELEASE_SHA" in check

    def test_the_release_pin_flow_is_gone(self):
        body = script()
        for retired in ("pin_ci", "pin_merge", "operations-release \\(", "gh pr merge", "OPERATIONS_BRANCH="):
            assert retired not in body, f"{retired!r} is still in the script"
        assert not (ROOT / "scripts" / "pin_lane.sh").exists()


class TestEnvironment:
    def test_it_holds_no_environment_specifics(self):
        body = script()
        assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b(?!\d)", body.replace("127.0.0.1", "")), (
            "an IP address is hardcoded in the script"
        )
        assert "id_rsa" not in body and "_ed25519" not in body, "an ssh key path is hardcoded"
        assert '"${KVM1_SSH:?' in body or "KVM1_SSH:?" in body
        assert "OPERATIONS_SHA" in body


class TestInstructions:
    def test_the_rule_names_its_only_exceptions(self):
        body = flowed()
        for opt_out in ("do not deploy", "local only", "pr only"):
            assert opt_out in body, f"the opt-out {opt_out!r} is not written down"
        for pause in ("credential", "destructive", "unrecoverable"):
            assert pause in body, f"the pause condition {pause!r} is not written down"

    def test_the_rule_says_where_a_task_actually_ends(self):
        body = flowed()
        assert "/version" in body and "healthy" in body and "live site" in body
        assert "do not stop at" in body

    def test_the_instructions_say_merging_releases_and_this_is_break_glass(self):
        body = flowed()
        assert "merging to operations main is a production release" in body
        assert "break-glass" in body


def _run(*args, **env):
    clean = {k: v for k, v in os.environ.items() if k not in {"OPERATIONS_SHA", "OPERATIONS_BRANCH", "KVM1_SSH"}}
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False,
        env={**clean, **{k: v for k, v in env.items() if v is not None}}, cwd=str(ROOT),
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
class TestArguments:
    def test_dry_run_prints_the_plan_and_changes_nothing(self):
        status = ["git", "-C", str(ROOT), "status", "--porcelain"]
        before = subprocess.run(status, capture_output=True, text=True, check=False).stdout
        result = _run("--dry-run", OPERATIONS_SHA="", KVM1_SSH="")
        assert result.returncode == 0, result.stderr
        for stage in STAGES:
            assert stage in result.stdout, f"{stage} missing from the plan"
        assert "merge to Operations main" in result.stdout
        after = subprocess.run(status, capture_output=True, text=True, check=False).stdout
        assert before == after, "--dry-run modified the working tree"

    def test_it_will_not_run_without_a_commit_and_says_how_releases_normally_happen(self):
        result = _run()
        assert result.returncode != 0
        assert "OPERATIONS_SHA" in result.stderr
        assert "merge to Operations main" in result.stderr

    def test_a_branch_is_no_longer_a_target(self):
        result = _run(OPERATIONS_BRANCH="fix/anything")
        assert result.returncode != 0
        assert "OPERATIONS_SHA" in result.stderr

    def test_it_rejects_a_short_sha(self):
        result = _run(OPERATIONS_SHA="53f6675", KVM1_SSH="nobody@invalid")
        assert result.returncode != 0
        assert "40-character" in result.stderr

    def test_it_rejects_an_unknown_flag(self):
        assert _run("--force").returncode != 0
