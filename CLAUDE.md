# Working in this repository

## The default end goal is live production

Every task here — bug fix, feature, UI change, configuration change — is
finished when it is **running and verified in production**, not when the code
is written, not when CI is green, and not when a PR is merged.

Carry on through the whole pipeline without being asked and without pausing for
approval between stages:

```
code → tests → PR → CI → merge → pin → CI → sync → build → deploy → verify
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
OPERATIONS_SHA=<40-hex> KVM1_SSH=user@host bash scripts/fix_and_deploy.sh
```

Stages, each idempotent and recorded so an interrupted run resumes rather than
repeating work or double-merging:

```
preflight pin pin_ci pin_merge sync build deploy verify
```

`--dry-run` prints the plan and changes nothing. `--restart` discards recorded
progress.

The script does **not** open or merge the Operations PR carrying the change
itself. That one needs a human-readable description and review. Everything
after it is mechanical, which is why it is automated.

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
