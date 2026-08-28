# Working in this repository

## The default end goal is live production

Every task here — bug fix, feature, UI change, configuration change — is
finished when it is **running and verified in production**, not when the code
is written, not when CI is green, and not when a PR is merged.

Carry on through the whole pipeline without being asked and without pausing for
approval between stages:

```
change → tests → Operations PR → CI → merge → pin PR → CI → merge → sync → build → deploy → verify
```

Do not stop at code, tests, PR, CI, merge, pin, or build. Those are steps, not
destinations. A reply that ends at "the PR is open" or "CI is running" is an
unfinished task, and so is one that ends at a green deploy without checking the
requested behaviour on the live site.

**Only give a final answer when all of these hold:**

- the change is live in production
- `/version` reports the expected commit
- every container in the compose project is healthy
- the behaviour that was actually requested is verified on the live site

### When not to deploy

Stop before deploying only if the request says **"do not deploy"**, **"local
only"**, or **"PR only"**.

Otherwise pause mid-pipeline only for:

- **credentials or manual login** — never enter passwords, MFA codes, or
  secrets; ask the person to do it
- **a destructive or genuinely high-risk action** — deleting production data,
  rewriting history, anything not recoverable by redeploying
- **an unrecoverable failure** — report what broke, with the evidence

Being unsure whether a change is worth deploying is not one of these. Ship it.

## How to deploy

```bash
# from a branch: opens the Operations PR, merges it, then ships it
OPERATIONS_BRANCH=fix/thing KVM1_SSH=user@host bash scripts/fix_and_deploy.sh

# or from a commit already on Operations main
OPERATIONS_SHA=<40-hex> KVM1_SSH=user@host bash scripts/fix_and_deploy.sh
```

Stages, each idempotent and recorded so an interrupted run resumes rather than
repeating work or double-merging:

```
ops_pr ops_ci ops_merge preflight pin pin_ci pin_merge sync build deploy verify
```

`--dry-run` prints the plan and changes nothing. `--restart` discards recorded
progress.

Given a branch, the script opens the Operations PR itself, with a description
assembled from that branch's commits, polls its checks, merges it when green
and carries straight on to the pin and the deploy. There is no manual gap.

It stops on a **merge conflict** rather than guessing: resolving one means
choosing which side of the change survives, and that is not a decision to
automate.

Re-running is safe, and not only because progress is recorded locally. Every
mutating stage asks the *remote* whether its effect is already there — branch
already merged, PR already open, anchor already moved, and production already
serving the target commit — so the skips survive losing the local state file.

`build` and `deploy` check production directly: the live `/version` must equal
the target commit, `8000/tcp` must be bound to `127.0.0.1:8210`, and every
container in the project must be healthy. All three, because a healthy
container with no 8210 binding still serves 502 through nginx. If they hold,
both stages skip and `verify` still runs; if any fails, the deploy proceeds
normally.

This repository holds no environment specifics — hostnames and paths come from
the environment (`KVM1_SSH`, `KVM1_SSH_KEY`, `PROD_ENV_FILE`), never from
committed files. Keep it that way.

## Invariants the pipeline protects

- **The release anchor and its contract test move in the same commit.**
  `docker-compose.production.yml` carries `operations: &operations-release
  <sha>` and `tests/test_production_compose_contract.py` asserts it. Changing
  one without the other lets a build be pinned to a commit the test still
  expects to be the previous one.
- **The source checkout must equal the anchor before any build.** Building a
  tree that is not what the anchor claims ships something no PR described.
  `sync` refuses on mismatch.
- **One deploy at a time.** `sync` refuses if a build or compose run is already
  in flight on the host.
- **Deploy with the project name and env file.** Omitting `-p` or
  `--env-file` produces orphan containers and a service with no port binding,
  which returns 502 while every container still reports healthy.

## Verifying

A green pipeline proves the release is running. It does not prove the change
does what was asked — check that in the browser, and say plainly which of the
two you actually confirmed. When a test cannot reach the real behaviour, say so
rather than letting a green run imply more than it demonstrated.
