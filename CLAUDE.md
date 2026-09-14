# Working in this repository

## The default end goal is live production

Every task here — bug fix, feature, UI change, configuration change — is
finished when it is **running and verified in production**, not when the code
is written, not when CI is green, and not when a PR is merged.

Carry on through the whole pipeline without being asked and without pausing for
approval between stages:

```
change → tests → PR → CI → merge → image → deploy → verify
```

Do not stop at code, tests, PR, CI, merge, or a green build. Those are steps,
not destinations. A reply that ends at "the PR is open" or "CI is running" is an
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

## How production is released

**Merging to Operations `main` is a production release.** Operations builds its
image once in CI and releases it through its own `.github/workflows/deploy.yml`:
the host's `teleautomation-deploy` pulls exactly that digest, refuses it unless
the image was built from the merged commit, restarts, verifies the running
image, `/version`, health, every container and the public site, and restores the
previous release on any failure. There is no pin, release PR or deploy command
in this repository. Follow the Operations `deploy` run to green, then verify the
change on the live site.

What this repository owns for production:

- `docker-compose.production.yml` — the stack. `operations-api` runs the image
  named in the host's `/etc/teleautomation/operations-release.env`, which only
  `teleautomation-deploy` writes.
- `deploy/production/teleautomation-deploy` — the only command the CI deploy key
  can run: `verify`, `deploy`, `deploy-local`, `rollback`, `status`, `init`.
- `scripts/setup_ci_deploy.sh` — the one-time keys, server account and GitHub
  security settings. It creates credentials and security configuration, so a
  person runs it; `--check` reports the state of every item.
- `scripts/fix_and_deploy.sh` — break-glass only, below.

Merging a change to these files does not change the host. The host's checkout of
this repository moves only when the break-glass `sync` runs or root pulls it
deliberately, and a changed `teleautomation-deploy` is installed only by
re-running `scripts/setup_ci_deploy.sh` (it replaces both keys). On the host, run
compose through `teleautomation-compose`, which always passes the release file;
bare `docker compose` resolves the host-built image name and `up` would replace
the verified release with it.

## Break-glass: releasing without CI

Only when GitHub Actions or the registry cannot release, and the release cannot
wait:

```bash
OPERATIONS_SHA=<40-hex> KVM1_SSH=user@host bash scripts/fix_and_deploy.sh
```

Stages, each recorded so an interrupted run resumes:

```
preflight sync build release
```

It releases only a commit already on Operations `main`, builds it on the host
from a checkout verified to be that commit, stamps it with the commit, and hands
it to `teleautomation-deploy deploy-local` — so the label check, verification
and automatic rollback are the ones every CI release gets, and the recorded
release stays true. `build` and `release` skip when production already serves
the commit from its recorded release. `--dry-run` prints the plan; `--restart`
discards recorded progress.

This repository holds no environment specifics — hostnames and paths come from
the environment (`KVM1_SSH`, `KVM1_SSH_KEY`, `PROD_ENV_FILE`) or, for CI
releases, from the Operations `production` environment, never from committed
files. Keep it that way.

## Invariants the release protects

- **An image runs only the commit it says it was built from.** Its revision
  label and baked `RELEASE_SHA` must both equal the requested commit before
  anything restarts.
- **One release at a time.** The Operations `production-release` concurrency
  group, a host lock, and a refusal while any `docker compose` or `docker build`
  runs on the host.
- **Every release is recorded and reversible.** The previous release is kept,
  restored automatically on failure, and restorable with
  `teleautomation-deploy rollback` or by releasing an older commit from the
  Operations deploy workflow.
- **Deploy with the project name and every env file.** Omitting `-p` or an
  `--env-file` produces orphan containers, a service with no port binding, or
  the wrong image — a 502 while every container still reports healthy.

## Verifying

A green pipeline proves the release is running. It does not prove the change
does what was asked — check that in the browser, and say plainly which of the
two you actually confirmed. When a test cannot reach the real behaviour, say so
rather than letting a green run imply more than it demonstrated.
