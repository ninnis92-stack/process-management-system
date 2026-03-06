# Secrets and CI variables

This file lists the repository / environment secrets expected by CI and staging deploys.

Repository secrets (add via GitHub UI → Settings → Environments → staging or via `gh`):

- `FLY_API_TOKEN` — Fly API token used by `flyctl` in CI.
- `FLY_APP` — Fly app name (e.g. `process-management-prototype-lingering-bush-6175`).
- `PLATFORM_API_TOKEN` — platform token (alias used in some scripts).
- `STAGING_DATABASE_URL` — Postgres connection string for staging DB.
- `STAGING_BASE_URL` — base URL for smoke tests (used by Cypress).
- `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET` — optional for automated backup uploads.

Optional monitoring / security env vars
- `SENTRY_DSN` — Sentry DSN for error reporting (scaffolded; inert when not set).
- `SENTRY_ENVIRONMENT` — environment tag for Sentry (staging/production).
- `SECURITY_HEADERS_ENABLED` — set to `true` to enable CSP/HSTS and secure cookie defaults.

Security notes
- Use organization or environment-level secrets where possible to restrict access.
- Prefer short-lived tokens and rotate regularly.
- Grant only `maintain` or `admin` roles to people who must set secrets; automate via a CI service account where possible.

CLI example: set secrets using `gh` (run locally):

```bash
REPO=your-org/your-repo
gh secret set FLY_API_TOKEN --body "$FLY_API_TOKEN" --repo "$REPO"
gh secret set FLY_APP --body "$FLY_APP" --repo "$REPO"
gh secret set STAGING_DATABASE_URL --body "$STAGING_DATABASE_URL" --repo "$REPO"
gh secret set STAGING_BASE_URL --body "$STAGING_BASE_URL" --repo "$REPO"
```
