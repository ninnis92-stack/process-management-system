# Staging deployment checklist

This file documents the safe staging deployment flow using the existing Fly app
`process-management-prototype-lingering-bush-6175` as the staging target.

Prerequisites
- Ensure you are authenticated with Fly (`flyctl auth login`).
- Ensure `gh` is authenticated locally if you plan to set GitHub secrets via CLI.
- CI/Repo secrets to set (recommended via GitHub Actions `staging` environment):
  - `PLATFORM_API_TOKEN` (Fly API token)
  - `STAGING_DATABASE_URL`
  - `STAGING_BASE_URL` (e.g. https://process-management-prototype-lingering-bush-6175.fly.dev)
  - Optional: `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET` for backups

Steps
1) Clear any existing smoke-test records on staging:

```bash
flyctl ssh console -a process-management-prototype-lingering-bush-6175 --command \
  "python3 -c \"from app import create_app;from app.extensions import db;from app.models import Request as R;app=create_app();ctx=app.app_context();ctx.push();q=R.query.filter(R.title.like('SMOKE_%'));count=q.count();q.delete(synchronize_session=False);db.session.commit();print('smoke_deleted',count);ctx.pop()\""
```

2) Deploy to staging (CI or local):

```bash
git push origin HEAD
flyctl deploy -a process-management-prototype-lingering-bush-6175
```

3) Verify basic health and endpoints:

```bash
curl -fsS https://process-management-prototype-lingering-bush-6175.fly.dev/health
curl -I https://process-management-prototype-lingering-bush-6175.fly.dev/
```

4) Run smoke tests (local or CI). Example local Cypress run:

```bash
npm ci
npx cypress run --spec cypress/e2e/smoke.spec.js --config baseUrl=${STAGING_BASE_URL}
```

5) Clear smoke records again (repeat step 1).

6) If staging is healthy, merge and tag a release on `main`:

```bash
git checkout main
git merge --no-ff <feature-branch>
git tag -a vYYYY.MM.DD -m "release: staging verified"
git push origin main --tags
```

Notes
- Add secrets via the GitHub UI (Settings → Environments → staging) or via `gh secret set`.
- Do not commit secrets to the repository.
- For automated backups, create an IAM user scoped to the S3 bucket and use those limited credentials.
