# PH-008: CI/CD safety, staged validation and release gates

**Status:** code and policy improvements are on the existing hardening branch, **not in** `main`. No production deployments, branch-protection mutations or Docker pushes were made.

## Automated checks

The workflow [`.github/workflows/python-tests.yml`](../.github/workflows/python-tests.yml) runs on PRs to `main`, pushes to `main` and explicit manual dispatch. Job names are stable and unambiguous: **`pytest`** and **`container-preflight`**. It uses `contents: read`, GitHub-maintained actions pinned to immutable SHA revisions, no `pull_request_target` and no deployment credentials.

### Required: pytest

- Uses Python 3.13, installs the same project package and dev dependencies with `pip install -e ".[dev]"`, then `pip check`.
- Creates ephemeral MongoDB 7 and two separate Redis 7 instances (cache 6379, protected state 6380) **on the CI runner only**.
- Applies the two Redis eviction policies independently, `allkeys-lru` and `noeviction`, using Docker commands against the CI service containers.
- Tests accept **only** the explicitly assigned loopback Mongo/Redis test URIs; they do not consult production `DATABASE_URI` or `REDIS_URI` for integration tests.
- Compiles `bot.py`, core, config, handlers, repositories, scripts and tests.
- Runs a high-signal Ruff check for undefined names (`F821`, `F822`, `F823`). The broader Ruff/style backlog is deliberately not a new mandatory gate until the existing codebase has been cleaned and measured.
- Runs the full test suite, including local MongoDB/Redis integration tests, and produces an XML coverage **baseline** artifact with 14-day retention. There is intentionally no fail-under threshold yet: review the actual baseline and agree a non-regression floor in a later PR.

### Required: container-preflight

- Creates a disposable, inert `.env` file solely to validate the Docker Compose schema, including the opt-in state Redis profile, then removes it.
- Builds the production Dockerfile to the **local CI runner image cache only**. Does not run the Telegram bot, contact the real database, publish the image, change remote infrastructure or deploy.
- Checks the image's configured user is `botuser` and that `AUTO_UPDATE` / `UPDATE_ON_START` default to `false`.

**On success, both jobs must appear green for the latest commit**. The GitHub Actions run itself reports the exact commit SHA and logs.

## Branch protection, requires repository owner/admin permissions

GitHub API could list rulesets and reported **zero repository rulesets** at inspection (2026-10-28). The integration could **not** read classic branch protection (`403 Resource not accessible by integration`). Therefore the current status of any classic branch protection is **unverified**. No repository settings were changed.

To enforce checks on `main`, a repository administrator should open:

[GitHub repository settings: Branches](https://github.com/rumalg123/Advanced-File-Filter-Bot/settings/branches)

1. Add or edit a rule for branch **`main`** (or use a matching repository ruleset).
2. Require pull requests before merging, and resolve PR conversations.
3. Select **Require status checks to pass before merging** and require the **`pytest`** and **`container-preflight`** checks from GitHub Actions. If GitHub lists names as `Python regression tests / pytest`, choose the actual check-run context displayed in the PR. If the check has not yet appeared, wait until the workflow has run successfully once.
4. Prefer **Require branches to be up to date before merging** if your workflow favors strict base freshness; evaluate tradeoff with active contributors.
5. Prevent force pushes and branch deletion. Consider disabling bypass for administrators; keep emergency procedures explicit.
6. Do not add `paths` or `paths-ignore` conditions to a workflow whose checks are required, because skipped checks can remain pending.
7. Verify in a disposable PR that an intentionally failed test blocks merge, then revert that test. Do not merge the test failure.

GitHub references:
- [Managing a branch protection rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule)
- [GitHub rulesets and required checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [OWASP DevSecOps repository hardening](https://owasp.github.io/DevSecOpsGuideline/2-Process/2-2-Develop/2-2-1-Pre-commit/2-2-1-4-Repository-Hardening/)

## Staging verification before production

1. Review the **current, successful CI run** for the exact commit proposed for merge. Capture code coverage % without overstating untested areas.
2. Deploy to a **separate staging environment** with test Telegram channels and distinct MongoDB/Redis datasets. Do not point staging at production credentials.
3. Verify private/group search, full filename/episode matching, pagination, file retrieval, bans, premium bypasses and quotas.
4. Force a MongoDB timeout and confirm the search error is retryable, does not cache a false empty result, then recovers.
5. If PH-003 split Redis is being enabled, complete migration and rollback rehearsal before switching `REDIS_STATE_URI`. Otherwise leave it unset.
6. If PH-005 durable queue is being enabled, verify a controlled worker crash/lease expiry, replay, duplicate behavior and dead-letter count, then leave it off by default until approved.
7. Test `/deleteall` preview, non-admin rejection, stale/replayed callback and short failure before enabling bulk deletion in the actual production release.
8. Verify startup, liveness, logs and alerting under the deployment network boundary. PH-004 monitoring endpoint authentication remains explicitly deferred by operator decision.
9. Record expected environment values without sharing secrets, backup timestamps, release artifact/commit SHA and rollback command.

## Deployment and rollback guardrails

The workflow **does not deploy** and does not automatically push to Docker registries. Production releases remain a **separate explicit operator action** after a successful reviewed/staged commit.

- Build and tag images from an immutable reviewed commit, not the mutable `main` tag alone.
- Do not enable `AUTO_UPDATE` or `UPDATE_ON_START` as part of this hardening rollout. A mutable runtime updater can bypass CI checks, so preserve `false` defaults unless separately audited.
- Verify image runtime user and inspect Compose resolved configuration locally. Never print resolved secrets in public CI logs.
- Take a compatible backup and retain the previous image before rolling out.
- Record a rollback trigger for database/Redis errors, wrong search results, lost callbacks, growing dead letters, or auth regressions.
- Restore application code/container image first; apply **database rollback only if an actual migration was performed**. The PH-001..PH-008 default path makes no existing MongoDB schema changes.
- Never claim a successful CI run proves that Redis migration, bulk deletion, or a production dataset has been validated end-to-end.

## Remaining PH-008 work

- Verify or configure actual `main` branch-protection required checks via a GitHub admin.
- Review the real coverage baseline, and choose a reasonable `--cov-fail-under` non-regression threshold on a subsequent PR.
- Add a deployment-target-specific smoke-test harness only after staging credentials and approval are available. There is no deployment action in this workflow.
- Optionally tighten full-codebase lint, dependency pinning, SBOM/image vulnerability scans and trusted artifact provenance after documenting the current baseline.

**Release status is deliberately not "Verified" until required checks are enforced on `main` and staging validation is supplied.**
