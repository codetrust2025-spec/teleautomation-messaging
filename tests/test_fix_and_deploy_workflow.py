"""The deploy pipeline is written down once and automated once.

Production deployment is the default end goal for every change in this project,
so the sequence that gets there cannot live only in someone's head or in a
prompt pasted per task. It lives in ``CLAUDE.md`` (what an agent must do) and
``scripts/fix_and_deploy.sh`` (how it is actually done).

Two documents describing one pipeline drift. These tests tie them together: the
stage list in the script and the stage list in the instructions must be the same
list, so adding a stage to one without the other fails here rather than at 2am
against production.

They also hold the line the READMEs take about environment specifics. Neither
repository names a host, an IP or a key path; those arrive through the
environment. A convenience default committed "just for now" is how a production
address ends up in a repo permanently, so the script is asserted to contain
none.
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

STAGES = [
    "ops_pr", "ops_ci", "ops_merge",
    "preflight", "pin", "pin_ci", "pin_merge",
    "sync", "build", "deploy", "verify",
]


def script() -> str:
    assert SCRIPT.exists(), "the deploy pipeline has no script"
    return SCRIPT.read_text(encoding="utf-8")


def instructions() -> str:
    assert INSTRUCTIONS.exists(), "the deploy rule has no written home"
    return INSTRUCTIONS.read_text(encoding="utf-8")


def test_the_script_declares_every_stage_in_order():
    match = re.search(r"^STAGES=\(([^)]*)\)", script(), re.M)
    assert match, "no STAGES declaration to check"
    assert match.group(1).split() == STAGES


def test_the_instructions_list_the_same_stages_in_the_same_order():
    """Two descriptions of one pipeline drift unless something ties them.

    Matched against the explicit stage block rather than scanning the whole
    document: the prose above it says "code → tests → PR → CI → merge → pin",
    so a naive search finds "pin" in the summary long before the real list and
    reports an order problem that is not there.
    """
    blocks = re.findall(r"```[a-z]*\r?\n(.*?)\r?\n```", instructions(), re.S)
    listed = [b.split() for b in blocks if set(STAGES) <= set(b.split())]
    assert listed, "CLAUDE.md has no block listing every stage"
    assert listed[0] == STAGES, "the stage block does not match the script"


def test_every_stage_has_an_implementation():
    body = script()
    for stage in STAGES:
        assert re.search(rf"^run_{stage}\(\)", body, re.M), f"{stage} is named but not implemented"


def test_the_run_loop_walks_the_declared_stages():
    """A hand-written call sequence would silently diverge from STAGES."""
    assert re.search(r'for stage in "\$\{STAGES\[@\]\}"', script())


def test_progress_is_recorded_so_an_interrupted_run_resumes():
    body = script()
    assert "done_already" in body and "mark_done" in body
    assert re.search(r"if done_already .*; then", body), "completed stages are not skipped"


def test_it_refuses_a_commit_that_is_not_on_operations_main():
    """Deploying a commit that was never merged ships something no PR
    described, and it cannot be found again from main."""
    assert "merge-base --is-ancestor" in script()


def test_it_refuses_when_the_anchor_and_checkout_disagree():
    """The compose file requires the source checkout to be verified at the
    anchored commit before any build."""
    body = script()
    assert 'ANCHOR" = "$HEAD' in body or '"$ANCHOR" = "$HEAD"' in body


def test_it_refuses_to_deploy_over_a_running_deploy():
    assert "another deploy is already running" in script()


def test_the_anchor_and_its_contract_test_move_together():
    """Moving one without the other pins a build to a commit the test still
    expects to be the previous one."""
    body = script()
    assert "CONTRACT_TEST=" in body
    sed = re.search(r"^\s*sed -i .*OPERATIONS_SHA.*$", body, re.M)
    assert sed, "no anchor rewrite found"
    assert "CONTRACT_TEST" in sed.group(0), "the contract test is not rewritten with the anchor"


def test_verification_checks_version_health_containers_and_public():
    body = script()
    assert "/version is" in body, "no /version assertion"
    assert "health not ok" in body
    assert "containers healthy" in body
    assert "public returned" in body


def test_it_holds_no_environment_specifics():
    """The README says hostnames are supplied per deployment. A convenience
    default committed 'just for now' is how an address becomes permanent."""
    body = script()
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b(?!\d)", body.replace("127.0.0.1", "")), (
        "an IP address is hardcoded in the deploy script"
    )
    assert "id_rsa" not in body and "_ed25519" not in body, "an ssh key path is hardcoded"
    for required in ("KVM1_SSH", "OPERATIONS_SHA"):
        assert f'"${{{required}' in body or f"{required}:?" in body, (
            f"{required} is not required from the environment"
        )


def flowed() -> str:
    """The instructions with markdown emphasis and line wrapping removed.

    A phrase like ``**"local only"**`` can wrap mid-phrase, so searching the
    raw text finds nothing while the document plainly says it.
    """
    return re.sub(r"\s+", " ", instructions().replace("*", "").replace('"', "")).lower()


def test_the_rule_names_its_only_exceptions():
    """A rule with vague exceptions is a rule that gets talked out of."""
    body = flowed()
    for opt_out in ("do not deploy", "local only", "pr only"):
        assert opt_out in body, f"the opt-out {opt_out!r} is not written down"
    for pause in ("credential", "destructive", "unrecoverable"):
        assert pause in body, f"the pause condition {pause!r} is not written down"


def test_the_rule_says_where_a_task_actually_ends():
    body = flowed()
    assert "/version" in body
    assert "healthy" in body
    assert "live site" in body
    assert "do not stop at" in body


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_dry_run_prints_the_plan_and_changes_nothing():
    before = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    ).stdout
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True, text=True, check=False,
        # Deliberately no OPERATIONS_SHA or KVM1_SSH: the plan must be printable
        # before anything is configured, or nobody will run it first.
        env={**os.environ, "OPERATIONS_SHA": "", "KVM1_SSH": ""},
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    for stage in STAGES:
        assert stage in result.stdout, f"{stage} missing from the plan"
    after = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    ).stdout
    assert before == after, "--dry-run modified the working tree"


def _run(**env):
    clean = {k: v for k, v in os.environ.items()
             if k not in {"OPERATIONS_SHA", "OPERATIONS_BRANCH", "KVM1_SSH"}}
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True, check=False,
        env={**clean, **{k: v for k, v in env.items() if v is not None}},
        cwd=str(ROOT),
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_it_will_not_run_without_a_target():
    result = _run()
    assert result.returncode != 0
    assert "OPERATIONS_BRANCH" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_it_rejects_a_short_sha():
    """A short sha would pass a naive check and then fail against the anchor,
    which compares full hashes.

    Arguments are checked before the environment, so this reports the malformed
    sha rather than whatever else happens to be missing. CI has no Operations
    checkout beside this repository, and the first version of this script
    checked for that first - so the run died with 'Operations repo not found'
    and this test failed while describing the wrong problem entirely.
    """
    result = _run(OPERATIONS_SHA="53f6675", KVM1_SSH="nobody@invalid")
    assert result.returncode != 0
    assert "40-character" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_a_branch_alone_is_a_valid_target():
    """The whole point of the extension: hand it a branch and it opens the
    Operations PR itself. It must get past argument validation without a sha."""
    result = _run(OPERATIONS_BRANCH="fix/anything")
    assert "OPERATIONS_BRANCH" not in result.stderr, result.stderr
    assert "KVM1_SSH" in result.stderr, "should now be asking for the next missing thing"


def test_it_opens_the_operations_pr_from_the_branch_commits():
    """A generated description should quote the commits, which were written to
    explain the change, rather than invent a summary of them."""
    body = script()
    assert "run_ops_pr()" in body
    assert "origin/main..origin/$OPERATIONS_BRANCH" in body
    assert "pr create" in body


def test_rerunning_never_opens_a_second_pr_or_repeats_a_merge():
    """Idempotency is the property that makes resuming safe. Each mutating
    stage asks the remote whether its effect is already present."""
    body = script()
    assert "already merged into main" in body
    assert "already open — reusing it" in body
    assert "pin PR already open — reusing it" in body
    assert "anchor on main is already" in body


def test_the_resolved_commit_survives_a_resume():
    """If the merge commit were re-derived on resume, the deploy half could
    drift onto a different commit than the one that was merged."""
    body = script()
    assert "SHA_FILE=" in body
    assert '> "$SHA_FILE"' in body
    assert 'cat "$SHA_FILE"' in body


def test_build_and_deploy_ask_production_before_acting():
    """The recorded stage list is local. Delete it and the script would rebuild
    and recreate a container that is already correct, restarting a healthy
    service for nothing. Both stages check production itself, so the skip
    survives losing local state."""
    body = script()
    assert "production_matches_target()" in body, "no remote check exists"
    for stage in ("run_build", "run_deploy"):
        block = body.split(f"{stage}() {{", 1)[1].split("\n}", 1)[0]
        assert "production_matches_target" in block, f"{stage} does not consult production"


def test_the_remote_check_requires_version_binding_and_health():
    """Matching /version alone is not enough: a healthy container with no 8210
    binding still serves 502 through nginx, and a container outside this
    compose project is not the one a deploy would replace."""
    block = script().split("production_matches_target() {", 1)[1].split("\nREMOTE\n", 1)[0]
    assert "/version" in block
    assert "127.0.0.1:8210" in block
    assert "com.docker.compose.project" in block
    assert "healthy" in block


def test_the_remote_check_refuses_when_no_commit_is_known():
    """Without a resolved commit there is nothing to compare, and returning
    'matches' would skip a deploy that had never happened."""
    block = script().split("production_matches_target() {", 1)[1].split("\nREMOTE\n", 1)[0]
    assert '[ -n "$OPERATIONS_SHA" ] || return 1' in block


def test_verify_still_runs_when_build_and_deploy_are_skipped():
    """Skipping work must not skip the check that production is actually
    right — that is the only stage proving the claim."""
    body = script()
    verify_block = body.split("run_verify() {", 1)[1].split("\nREMOTE\n", 1)[0]
    assert "production_matches_target" not in verify_block, (
        "verify must not short-circuit on the same check it exists to make"
    )


def test_a_merge_conflict_stops_rather_than_guessing():
    """Resolving a conflict means choosing which side of the change survives.
    That is not a decision to automate."""
    body = script()
    assert "mergeStateStatus" in body
    assert "DIRTY" in body
    assert "merge conflict" in body
