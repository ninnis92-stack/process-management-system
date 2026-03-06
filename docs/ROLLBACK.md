# Rollback runbook

If a deployment causes a regression or critical failure, follow these steps to rollback to the previous release.

1. Identify the previous image/release tag used by Fly. Get recent deploys:

```bash
flyctl releases -a process-management-prototype-lingering-bush-6175
```

2. Roll back to a specific release id (example):

```bash
flyctl releases rollback -a process-management-prototype-lingering-bush-6175 <RELEASE_ID>
```

3. If DB migrations were applied and rollback is required:

- Restore DB from a recent backup (S3 or local snapshot).
- If using Alembic, consider creating a new downgrade migration rather than auto-downgrading; test locally first.

4. Notify stakeholders and open an incident ticket with the failure details, logs, and steps taken.

5. After rollback, run smoke tests and verify health:

```bash
curl -fsS https://process-management-prototype-lingering-bush-6175.fly.dev/health
# run smoke test suite if available
```
