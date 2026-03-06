# Production readiness checklist

This checklist captures operational actions to complete before promoting staging to production.

Infrastructure
- Provision managed Postgres for staging & prod and store connection strings in secrets.
- Configure S3 for backups and create an IAM user with least privilege.

Security
- Enable SSO with MFA for admin users (`SSO_ENABLED=true`, `SSO_REQUIRE_MFA=true`).
- Add `SENTRY_DSN` and enable Sentry alerts.
- Enable `SECURITY_HEADERS_ENABLED=true` to enforce CSP/HSTS.

CI & Deploy
- Wire GitHub Actions secrets for staging and prod.
- Ensure migrations are applied via Alembic in the release step.
- Configure health checks and readiness probes.

Monitoring & Backups
- Configure Sentry and set alerting rules.
- Schedule backups using `scripts/backup_dryrun.sh` and the S3 upload script (when creds available).

Validation
- Run load tests (`k6`) and E2E (Cypress) smoke tests in CI.
- Perform a canary/rolling deploy and validate before full promotion.
