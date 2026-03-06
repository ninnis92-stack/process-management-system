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
