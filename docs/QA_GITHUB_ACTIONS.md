# GitHub Actions: QA branch and real Telegram smoke

This runbook applies only to the public repository's `QA` branch. The existing
production-hardening branch and `main` remain unchanged. The live job is
**off by default** and must not be enabled until the QA credentials, Telegram
chats and environment protections are independently verified.

## Trigger and trust boundary

* `.github/workflows/python-tests.yml` checks PRs into `QA` (and `main`)
  without any Telegram secrets. Its jobs are `pytest` and `container-preflight`.
* `.github/workflows/telegram-e2e.yml` starts on a push to `QA` (including a
  completed merge) or an explicit manual dispatch on `QA`. A secret-free
  bootstrap check always runs.
* The authenticated job runs **only when the repository-level Actions variable
  `QA_LIVE_ENABLED` is exactly `true`**. When unset or `false`, the job is
  skipped and no environment secrets are used.
* Authenticated jobs reference environment `telegram-qa`, restricted to the
  `QA` branch. Environment branch restrictions alone are not a substitute
  for reviewing changes to workflows, dependencies or QA scripts.
* Do not enable `pull_request_target` or allow unreviewed PRs to invoke
  authenticated Telegram jobs. Use GitHub-hosted runners, not a persistent
  self-hosted runner on a production VPS.
* Concurrency prevents overlapping QA sessions; GitHub can replace an older
  **pending** run with a newer pending run. CI does not guarantee that every
  intermediate merge executes a separate live run.

## Before setting secrets

1. Create two **disposable Telegram test accounts** (admin and normal user)
   that do not control production groups or channels.
2. Create a separate bot with BotFather. Never reuse production bot token.
3. Create distinct private QA group, index channel and log channel. Add both
   user accounts to the group and add the bot with the required rights.
4. Generate WZGram session strings locally, confirm both accounts can connect,
   and store them only in GitHub environment secrets. Do not commit strings,
   copy them to issues, PR descriptions, workflow logs, or upload session files.
5. Independently verify that the QA bot token and chat IDs differ from production.
   The CI runner has no production configuration and cannot make that comparison.

## GitHub settings

In **Settings > Environments > telegram-qa**, restrict deployment branches to
exactly `QA`. Add these **environment secrets**:

| Name | Value |
| --- | --- |
| `QA_BOT_TOKEN` | Dedicated QA bot token |
| `QA_API_HASH` | Telegram API hash associated with test API ID |
| `QA_ADMIN_SESSION` | Test admin WZGram session string |
| `QA_USER_SESSION` | Test normal-user WZGram session string |

Add these **environment variables**:

| Name | Value |
| --- | --- |
| `QA_API_ID` | Test Telegram API ID, positive integer |
| `QA_OWNER_ID` | Telegram user ID of the **test admin session** |
| `QA_BOT_USERNAME` | Dedicated bot username, optionally prefixed with @ |
| `QA_GROUP_ID` | Dedicated QA supergroup ID such as -100... |
| `QA_CHANNEL_ID` | Dedicated QA index channel ID |
| `QA_LOG_CHANNEL_ID` | Dedicated QA log channel ID |

The three numeric chat IDs must be different. The admin WZGram session must
belong to the exact user specified by `QA_OWNER_ID`.

Separately, in **Settings > Secrets and variables > Actions > Variables**,
create the **repository-level** variable:

`QA_LIVE_ENABLED=false`

This must be a repository variable rather than only an environment variable,
because the job-level conditional is evaluated before the environment is
attached. After the first secret-free workflow run and credential review,
change it to `true`. Changing a variable does not itself create a workflow
run; merge a reviewed PR into `QA` or dispatch the workflow with ref `QA`.

Never set `QA_LIVE_ENABLED` in a PR or commit it to source code.

## Before the first authenticated run

1. Merge the QA bootstrap PR after the secret-free `pytest` and
   `container-preflight` jobs succeed.
2. Go to **Actions > Telegram QA E2E** and inspect the secret-free bootstrap
   result. Live smoke must be skipped while the variable is disabled.
3. Confirm the GitHub `telegram-qa` environment actually restricts deployments
   to `QA`. Confirm all four secrets and six environment variables are present.
4. Confirm the QA bot can send messages to each user privately. Both user
   accounts must have started/contacted the bot at least once where required
   by Telegram, and both must be in the QA group.
5. Set repository variable `QA_LIVE_ENABLED=true`. Trigger a manual run on
   branch `QA`, then verify an ordinary PR merge into `QA` triggers the
   next run automatically.

## What the first live stage actually exercises

The runner installs this bot under Python 3.13, starts isolated local MongoDB 7
and Redis 7, runs the fail-closed `scripts/qa_ci_guard.py` check, launches
`bot.py`, and waits for `/ready`. Then the E2E pytest creates two in-memory
WZGram clients using the protected session strings. It confirms their identities,
their access to the QA group, the bot's identity, and **real replies to concurrent
`/start` requests from both test accounts**.

This is a **smoke test**, not full QA coverage. The comprehensive historical
live evidence in `docs/qa/coverage-expansion/STATUS.md` is not currently
reproduced by committed E2E scripts. Add independent bounded test modules for
indexing, filters, pagination, callbacks, quota, permissions, concurrent
mutations, and Redis/MongoDB outages over subsequent reviewed PRs. Every
destructive test needs scoped fixtures and fail-safe cleanup.

The isolated database starts empty, so tests needing indexed media must create
their own fixtures. No production Atlas database, external Redis, server, or
production Telegram chat is used.

## Failures and security

* Never print environment variables, Telegram messages, session strings,
  API hashes, resolved Compose output, or complete bot logs in public Actions.
  The workflow keeps the bot log private to the temporary runner and deletes
  it on cleanup. Review Python test failure output for possible sensitive data.
* If secrets are missing, the guard fails with **variable names only**.
* A failure in bot readiness usually means startup configuration, Telegram
  connectivity, missing permissions, or backing-service initialization.
  Inspect with a private local reproduction, not by uploading raw CI logs.
* If a session is suspected of compromise, revoke its Telegram authorization
  promptly and replace the corresponding GitHub secret.
* Enforce `pytest` and `container-preflight` as required PR checks in the
  branch ruleset after the checks appear for a `QA` PR. Do **not** make the
  post-merge live job a required pre-merge check.
* All CI code, including dependencies, is capable of handling the live secrets
  while that job runs. Review every change before merging into the trusted branch.
* Automatic QA only reports a failure; it does not revert a merge or change
  production infrastructure.

References: [GitHub environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[workflow triggers](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
