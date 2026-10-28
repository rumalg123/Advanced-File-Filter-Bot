# Production hardening PR checklist

This project changes Telegram delivery, MongoDB media data and Redis state.
A passing unit test run is necessary but not sufficient for deployment.

## Code and evidence
- [ ] Source of truth updated in `PRODUCTION_HARDENING_TRACKER.md` with issue ID, code scope, test evidence and outstanding risks
- [ ] `pytest` and `container-preflight` both successful on the latest PR commit
- [ ] Review coverage baseline changes; document any significant decline (no blanket threshold until measured)
- [ ] New code includes regression tests and real local service integration tests where relevant
- [ ] Confirm no secrets, tokens, production DB dumps or Redis connection credentials in the PR

## Production compatibility
- [ ] Confirm whether any MongoDB document, collection or index **will** change, and provide migration/rollback if so
- [ ] Confirm Redis state and existing Telegram buttons survive a rolling restart; opt-in state routing requires a separately tested migration
- [ ] Verify new feature flags and auto-update remain off by default
- [ ] Test failure/restart behavior, permission checks, caching and destructive operations in staging
- [ ] Document data backup and recovery plan before any destructive behavior

## Release approval
- [ ] Explicit operator approval after staging smoke test (not granted by checking a box alone)
- [ ] Pin and record the exact commit/image digest, and retain the prior image for rollback
- [ ] Make changes in a maintenance window only if the specific release requires it
- [ ] Verify search, file delivery, premium/ban policy, pagination, Redis/Mongo reconnect and indexing after deployment
- [ ] Record monitoring checks and rollback trigger

See [CI/CD release gates](../docs/CI_CD_RELEASE_GATES.md). **Do not deploy or merge Draft PR #4 automatically.**
