# Operations Runbook

This document contains concise, repeatable steps for deploying, testing,
and maintaining the Process Management Prototype in production.

## Quick deploy

- Branch to deploy: `main`
- Tag format: `release-YYYY-MM-DD` (annotated)

Commands:

```bash
git checkout main
git pull origin main
git tag -a release-$(date -I) -m "Release $(date -I)"
git push origin --tags
flyctl deploy -a <app-name>
```

The `flyctl deploy` run uses `scripts/release_tasks.py` as the `release_command` to run migrations / schema fixes.

## Post-deploy smoke checks

Run these after the deployment completes:

```bash
curl -fsS https://<app>/health || echo "health failed" && exit 2
curl -fsS -I https://<app>/ | head -n 1
curl -fsS https://<app>/auth/login || echo "login failed" && exit 2
```

We've included `scripts/remote_smoke_check.sh` to run these checks automatically.

## Environment variables & secrets

Recommended secrets and env vars (non-exhaustive):

- `DATABASE_URL` — Postgres connection string
- `WEBHOOK_SHARED_SECRET` — HMAC secret for inbound webhooks
- `SENTRY_DSN` — optional error reporting
- `INVENTORY_DSN` — external inventory service DSN
- `ENABLE_EXTERNAL_VERIFICATION` — toggle (true/false)

On Fly use `fly secrets set KEY=VALUE` to store secrets.

## Migrations

We use Alembic where available. Typical workflow:

```bash
pip install alembic
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Before running migrations in production: take a DB backup (see Backup section).

## Rollback

If a deploy introduces critical failures:

1. Identify last working tag (e.g. `release-2026-02-28`).
2. Deploy that tag or its image:

```bash
git checkout tags/<previous-tag> -b rollback-temp
git push origin rollback-temp:main
flyctl deploy -a <app-name>
```

Or re-deploy the previous image via `flyctl` if available.

## Monitoring & synthetic checks

- Add a readiness probe hitting `/health`.
- Configure external uptime monitors (UptimeRobot, Pingdom) to alert on `/health` or the root endpoint.
- Integrate Sentry + Slack/PagerDuty for error alerting.

## Backups

Schedule regular DB backups. Example (Postgres):

```bash
# run on a trusted host with access to $DATABASE_URL
pg_dump -Fc "$DATABASE_URL" -f /backups/db-$(date -I).dump
```

Also back up persistent `uploads/` or storage buckets.

## Runbook checks to include in PRs

- Confirm migrations are present for schema changes.
- Ensure `ENABLE_EXTERNAL_VERIFICATION` remains off by default unless intended.
- Verify secrets are present in the target environment.

## Contact

Document primary on-call or team contacts here.

# Operations Runbook

This runbook documents quick operational commands for deploys, smoke tests, and rollbacks.

Prerequisites
- `flyctl` authenticated for your org
- `git` access to repository and permission to push to `staging` / `main`
- (CI) `FLY_API_TOKEN` stored in CI secrets for automated deploys

Common local commands

# Run the test suite
```
. .venv/bin/activate
python -m pytest -q
```

# Build and run locally
```
make install
python run.py
```

# Deploy to Fly (manual)
Replace `FLY_APP` with your target app (e.g., `process-management-prototype-staging`).

```
flyctl deploy -a <FLY_APP>
```

# Create staging app (Fly)
```
flyctl apps create process-management-prototype-staging --org <your-org>
# set secrets
flyctl secrets set DATABASE_URL=postgres://... FLY_ENV=staging
```

# Post-deploy smoke flow
1. Run `curl -fsS https://$FLY_APP.fly.dev/health` → expect `{"status":"ok"}`
2. Run `curl -I https://$FLY_APP.fly.dev/` → expect `200` or `302` depending on auth
3. Create smoke-record (inside instance):

```
flyctl ssh console -a $FLY_APP --command "python3 -c \"from app import create_app; from app.extensions import db; from app.models import Request as R; app=create_app(); ctx=app.app_context(); ctx.push(); r=R(title='SMOKE_TEST', request_type='both', pricebook_status='unknown', description='smoke', priority='medium', status='NEW_FROM_A', owner_department='B', submitter_type='guest'); r.ensure_guest_token(); db.session.add(r); db.session.commit(); print('created', r.id); ctx.pop()\""
```

4. Clean up smoke records before final redeploy:
```
flyctl ssh console -a $FLY_APP --command "python3 -c \"from app import create_app; from app.extensions import db; from app.models import Request as R; app=create_app(); ctx=app.app_context(); ctx.push(); cnt=R.query.filter(R.title.like('SMOKE_%')).delete(synchronize_session=False); db.session.commit(); print('deleted', cnt); ctx.pop()\""
```

Rollback
- Use Fly's dashboard to promote previous release or `flyctl releases` and `flyctl releases rollback <id>`.

Security checklist (pre-prod)
- Ensure `SECRET_KEY`, `DATABASE_URL`, `WEBHOOK_SHARED_SECRET` are set and rotated
- Enable `SSO_ENABLED` and `SSO_REQUIRE_MFA` for admin accounts where applicable
- Configure CSP, HSTS, and secure cookie flags in platform env
- Enable monitoring and alerting (Sentry, Prometheus, PagerDuty integrations)

Monitoring & backups
- Add Prometheus scraping for `/metrics` and set up a retention/alerting policy
- Back up database snapshots daily and test restore

Backup script

Use the provided helper script to create a Postgres dump and upload to S3:

```bash
# local run (writes to /tmp)
DATABASE_URL=postgres://user:pass@host/db AWS_S3_BUCKET=my-bucket ./scripts/db_backup.sh
```

E2E / Staging

- A staging GitHub Actions workflow (`.github/workflows/staging-deploy.yml`) will run tests and deploy to a Fly app configured via CI secrets (`FLY_API_TOKEN` and `FLY_APP`).
- A Cypress smoke job was added (`.github/workflows/cypress.yml`) that runs on pushes to `staging` and expects `STAGING_BASE_URL` in secrets. Configure the_SECRET in your repository settings before enabling.


Contact
- On-call: ops@example.com
- Repo: https://github.com/ninnis92-stack/process-management-system
