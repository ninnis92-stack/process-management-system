# Process Management Prototype

A small prototype app.

Administration: see `docs/ADMIN.md` for notes about the admin-managed Departments and SiteConfig (banner + rolling quotes). Tests covering these features live at `tests/test_admin_site_config.py`.

## Deployment & seeding (Fly.io)

Quick steps to deploy and ensure the demo users and DB are created on Fly:

1. Push your branch to the Git remote named `origin`:

  git add README.md
  git commit -m "docs: add deployment and seeding instructions"
  git push origin HEAD

2. Deploy to Fly:

  flyctl deploy -a process-management-prototype-lingering-bush-6175

  Note: The deployment `release_command` now runs Alembic migrations
  (`alembic upgrade head`) during releases. The app no longer relies on
  `db.create_all()` by default; `AUTO_CREATE_DB` is disabled in production
  images. If you want the old behavior for local testing set
  `AUTO_CREATE_DB=true` in your environment.

3. After deployment, open an SSH session to the running instance and run the
  seed script to create demo users (run as the app user in the container):

  flyctl ssh console -a process-management-prototype-lingering-bush-6175 --command "python3 seed.py"

  For ad-hoc maintenance you can still run the seeded release helper which
  invokes Alembic and then runs `seed.py` (when `SSO_ENABLED` is not set):

  flyctl ssh console -a process-management-prototype-lingering-bush-6175 --command "python3 scripts/release_tasks.py"

4. Confirm the app is healthy:

  curl -fsS https://process-management-prototype-lingering-bush-6175.fly.dev/health

If you need CI/CD automation, add these steps to your pipeline: push → `flyctl deploy` (migrations run via release_command) → optional `flyctl ssh` maintenance commands.
# FreshProcess Process Management Prototype

Brief architecture map for reviewers.

## Overview
- Flask app with blueprints: `auth` (login/SSO), `requests_bp` (core workflow), `external` (guest links), `notifications` (in-app notices).
- Data layer: SQLAlchemy models in `app/models.py`; migrations are not wired (tables auto-create in dev via `AUTO_CREATE_DB`).
Migrations:

 - The project does not include an Alembic scaffold by default, but a migration file has been added at `migrations/versions/0001_add_is_admin.py` which adds the `is_admin` column to the `user` table.

 - Recommended workflow (one-time setup):

```bash
pip install Flask-Migrate alembic
export FLASK_APP=run.py
flask db init        # only if you haven't initialized migrations
flask db migrate -m "add is_admin to user"
flask db upgrade
```

## Scheduling & Nudges

- Automated nudges for high-priority requests: enable from the Admin -> Special Emails page (`High-priority nudges`). Set the reminder interval in hours (default 24).
- A small cron example is provided at `scripts/cron_examples.sh` showing how to run the nudge sender hourly and refresh Prometheus gauges periodically. Adjust paths and virtualenv activation to match your environment or use your platform's scheduler.
- Run nudges manually for testing:

```bash
FLASK_APP=app flask notify-nudges
```

- Refresh metrics (owner counts and overdue gauge):

```bash
python3 -c "from app import create_app; from app.metrics import update_owner_gauge; from app.extensions import db; app=create_app(); ctx=app.app_context(); ctx.push(); from app.models import Request as ReqModel; update_owner_gauge(db.session, ReqModel); ctx.pop()"
```

These hooks are safe to run in development and can be scheduled by your host (cron, Fly scheduled jobs, Heroku Scheduler, etc.).

If you prefer not to use Flask-Migrate, you can apply the SQL directly for SQLite:

```bash
sqlite3 instance/dev.sqlite3 "ALTER TABLE user ADD COLUMN is_admin INTEGER DEFAULT 0;"
```

Debug workspace cleanup (cron example)
-----------------------------------

To periodically remove old admin-created debug requests (`is_debug=True`) you can schedule a simple maintenance job. Below is an example cron entry that runs a small Flask one-liner to delete debug requests older than 7 days. Adjust the venv activation and working directory to match your host.

```cron
# Run nightly at 03:30 UTC: delete debug requests older than 7 days
30 3 * * * cd /path/to/process-management-prototype && /path/to/venv/bin/python3 - <<'PY'
from app import create_app
from app.extensions import db
from app.models import Request
from datetime import datetime, timedelta
app = create_app()
with app.app_context():
  cutoff = datetime.utcnow() - timedelta(days=7)
  old = Request.query.filter(Request.is_debug==True, Request.created_at < cutoff).all()
  for r in old:
    db.session.delete(r)
  db.session.commit()
  print(f"Deleted {len(old)} debug requests")
PY
```

If you prefer using the HTTP endpoint, you can call the admin-only `/admin/debug/cleanup` endpoint, but ensure you authenticate the call (for example with a short-lived admin API token or a script that runs inside the app context). The endpoint requires `confirm=true` and accepts an optional `days` parameter.

TOTP 2FA (local accounts):

 - This project now includes optional TOTP 2FA for local accounts using `pyotp`.
 - To enable in your environment: `pip install pyotp`
 - Users can enable 2FA from their account via `/auth/totp/setup` (logs in required).
 - During login, users with 2FA enabled are prompted to verify the TOTP code.

```
- Frontend: Jinja templates under `app/templates`, static assets under `app/static`.
- Auth: Local login with optional OIDC SSO (see env vars below). Login required for all internal routes.
- Roles: Departments A/B/C drive status transitions and UI hints. Guests can view via tokenized links.

## Quickstart
- Create and activate a virtualenv, then install deps: `pip install -r requirements.txt`.
- Set `FLASK_ENV=development` and `AUTO_CREATE_DB=1` (or set `DATABASE_URL` to point to Postgres/MySQL).
- Seed local data (users, requests, artifacts) with `python3 seed.py`.
- Run the app with `python3 run.py`; default server binds to 0.0.0.0:8080 (see `run.py`).
- Uploads land in `uploads/`; adjust `UPLOAD_FOLDER` env var if needed.

Makefile conveniences
- Use the provided `Makefile` for common tasks inside development or Codespaces:

```bash
# install dependencies
make install

# run the Flask dev server
make run

# seed the DB
make seed

# run tests
make test

# run alembic migrations (requires alembic setup)
make migrate

# deploy to Fly (requires flyctl auth and access)
make deploy FLY_APP=process-management-prototype-lingering-bush-6175
```

CI
- A GitHub Actions workflow is included at `.github/workflows/ci.yml` which runs tests on push and pull requests to `main`.


## Metrics (Prometheus)

- The app exposes Prometheus-format metrics at `/metrics` (text exposition). A small DB-backed
  human-friendly view is available at `/metrics/ui` and a machine-friendly JSON endpoint at
  `/metrics/json` (supports `?range=daily|weekly|monthly|yearly`).
- `app/metrics.py` contains counters and a gauge used by the application. The dependency on
  `prometheus_client` is optional for local/dev runs — if the package is not installed the app
  uses a safe noop fallback so the server can start. To enable full Prometheus support, install:

```bash
pip install prometheus_client
```


## Status Labels & Workflow
- Status flow: NEW_FROM_A → B_IN_PROGRESS → (optional) PENDING_C_REVIEW (owned by C) → C_APPROVED/C_NEEDS_CHANGES → B_FINAL_REVIEW → SENT_TO_A (owned by A) → CLOSED.
- WAITING_ON_A_RESPONSE: Dept B is waiting on Department A; displayed as an informational badge.
- UI labels surface friendlier names for key statuses:
  - NEW_FROM_A: "Pending review from Department A"
  - PENDING_C_REVIEW: "Under review by Department C"
  - B_IN_PROGRESS: "In progress by Department B"
- Transitions are guarded in `app/requests_bp/workflow.py` and `is_transition_valid_for_request` in `routes.py`.

## Artifacts & Request Types
- Request types: `part_number`, `instructions` (displayed as "Method"), or `both`.
- Artifacts store as `artifact_type` = `part_number` or `instructions`; UI shows "Part Number" / "Method". No DB migration performed; the stored value remains `instructions`.
- Validation rules:
  - Method: donor and target part numbers required; no donor-reason allowed.
  - Part Number: donor required unless reason is `needs_create`; donor + reason together are rejected.
  - Due date must be at least 48 hours out.
- Artifact URLs: `instructions_url` column holds the Method URL; templates label it as "Method URL".

## Key Flows
- Request lifecycle statuses (owned by Dept B unless noted):
  - NEW_FROM_A → B_IN_PROGRESS → (optional) PENDING_C_REVIEW (owned by C) → C_APPROVED/C_NEEDS_CHANGES → B_FINAL_REVIEW → SENT_TO_A (owned by A) → CLOSED.
  - WAITING_ON_A_RESPONSE: Dept B waiting on Department A; informational badge.
- Transitions are guarded in `app/requests_bp/workflow.py` and `is_transition_valid_for_request` in `routes.py`.
- Handoffs: When moving to C or back to A, a submission packet with summary/details (and optional images) is required.

## Auth & SSO
- Local login fallback always available (`/auth/login`).
- OIDC SSO optional: set `SSO_ENABLED=true` and provide `OIDC_DISCOVERY_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` in environment.
- SSO init lives in `app/auth/sso.py`; routes in `app/auth/routes.py`.
SSO & 2FA:

- The app includes a minimal OIDC integration scaffold in `app/auth/sso.py`. SSO is disabled by default. Enable it with these config values:

```
SSO_ENABLED=true
OIDC_DISCOVERY_URL=https://your-idp/.well-known/openid-configuration
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_REDIRECT_URI=https://your-app/_auth/oidc/callback
```

- If your IdP communicates MFA in the `amr` claim, set `SSO_REQUIRE_MFA=true` to require MFA for admin access. The SSO flow sets `session['sso_mfa']` when it detects MFA in the id_token. Until your IdP is connected, SSO and MFA checks are inert.

### Enforcing SSO for Guest Submissions (integration notes)

- The app supports enforcing that guest submissions come from accounts already linked to your SSO provider. This is controlled by the `REQUIRE_SSO_FOR_GUEST` config flag (disabled by default).
- When enabled the guest email provided on the `/external/new` form must match a `User` row whose `sso_sub` is populated (i.e. previously linked via SSO). If the email is not SSO-linked the form will show a friendly warning and the request will not be created.
- To integrate: during your SSO onboarding flow ensure you create or update a local `User` with `email` and `sso_sub` set. Then enable `REQUIRE_SSO_FOR_GUEST=true` in your deployment environment to enforce the restriction.

Smoke-test helper (placeholder): `scripts/smoke_sso_submit.py` is included to assist with later automation once you have test SSO cookies or an automated SSO test flow. It expects `SSO_TEST_COOKIE` and `SSO_TEST_EMAIL` env vars and demonstrates how to POST the guest form while authenticated.

Admin Hardening Checklist:

- Enable SSO and test with a non-production IdP before enforcing in production.
- Use `SSO_REQUIRE_MFA=true` to enforce MFA for admins when your IdP reports it.
- Audit logs are viewable at `/admin/audit` once signed-in as an admin.

- Admin navbar: the top-right admin banner includes a quick department selector that
  allows admins to view any department's dashboard (`/dashboard?as_dept=A|B|C`) without
  starting an impersonation session. This is a view-only shortcut; to start acting-as a
  department use the impersonation controls under the Admin UI.

## Notifications
- Stored in DB via `Notification` model; created via `notify_users` helper in `requests_bp/routes.py`.
- Types include status changes, nudges, and request creation; surfaced in UI banner (template logic in `base.html`).

Behavior notes:
- Clicking the notifications icon in the header now marks all unread notifications as read and clears the red badge immediately (endpoint: `POST /notifications/mark_all_read`).
- When email delivery is enabled (configure `EMAIL_ENABLED` and SMTP settings), recipients with an email address will receive email messages instead of creating duplicate in‑app `Notification` rows. This prevents duplicate delivery paths once your mailer is active.
- SSO-linked users are treated the same: if email integration is active, a notification that would previously have been an in‑app event will instead attempt to send an email to the user's registered address.

Testing locally:
- A small test script is available at `scripts/notify_test.py` to exercise `notify_users()` with `EMAIL_ENABLED` toggled. Run with:

```bash
PYTHONPATH=. python3 scripts/notify_test.py
```

This script will create temporary test users and print counts of in‑app `Notification` rows created when email is disabled vs enabled.

## Search & Filtering
- Search endpoint `/search` supports request-number lookup (`id`) plus keyword search across request/public fields (`title`, `description`, `request_type`, `pricebook_status`, `sales_list_reference`, artifact fields, and public submissions).
- By default, comment bodies are excluded from search (private/internal comment scopes are not indexed by search).
- Dept B dashboard shows status buckets and semantic filters (in progress, C review, final review, etc.). Closed items >24h are hidden.

## Nudges
- Nudges are automated reminders for high-priority requests that are still open for the assigned user.
- Admin can enable/disable nudges and control the timer interval in the admin special-email settings.
- A default minimum delay of 4 hours after request creation is enforced before nudges begin; admin can only extend that delay.
- User-driven nudge pushing is disabled by default; nudges are intended to be timer-driven by admin configuration.

## Reject Request
- The assigned user can reject a request with a required rejection reason.
- Rejection closes the request and posts a public rejection comment for visibility across handoffs.
- The reject button label is admin-editable and defaults to `Reject Request`.
- Admin can enable/disable the reject feature and configure which departments can use it.
- Default behavior: only Dept B has reject enabled.

## Deploy Smoke Hygiene
- For release verification, run deployed smoke checks after deploy and clear smoke test records before final redeploy to keep production validation clean.

## Forms & Validations
- WTForms in `app/requests_bp/forms.py` drive request create/edit/transition forms.
- File uploads stored under `UPLOAD_FOLDER`; only PNG/JPEG/WebP allowed; 10MB per file; `MAX_FILES_PER_SUBMISSION` controls count.

## Guest Access
- Guest tokens created per request (`Request.ensure_guest_token`). Guests can view/update via `external` blueprint using tokenized links.

## Environment
- Copy `.env.example` (if present) or set env vars: `FLASK_ENV`, `DATABASE_URL` (or default SQLite), `SECRET_KEY`, `UPLOAD_FOLDER`, `AUTO_CREATE_DB`.
- Optional: `SSO_ENABLED`, `OIDC_*` vars for SSO.

### Integrations (prototype-friendly)
- Email: set `EMAIL_ENABLED=true` and provide SMTP settings (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`) to enable real email sending. By default the app logs email contents to the application logger for prototype testing.
- Ticketing: set `TICKETING_ENABLED=true` and `TICKETING_URL`/`TICKETING_TOKEN` to enable creating tickets in an external system. When disabled the app returns prototype ticket ids.
- Part/Method verification APIs: set `PART_API_ENABLED`/`METHOD_API_ENABLED` and respective `*_API_URL`/`*_API_TOKEN` to enable remote validation. When disabled the verification endpoint logs and returns non-blocking feedback.

## External Integrations & Extensibility

- The application is designed to integrate with external management systems (PM tools, ticketing, and verification databases). Integration options include:
  - Email hooks: real email sending (SMTP) can be enabled and used by downstream systems to create tasks or tickets.
  - Ticketing adapters: configure `TICKETING_ENABLED`, `TICKETING_URL`, and `TICKETING_TOKEN` to post structured tickets when a status transition or handoff occurs.
  - Webhooks: administrators can wire webhooks (or consume the `notify_users` output) to notify external services when transitions occur — the admin-configurable `StatusOption` controls when notifications should be emitted (always / on transfer only / disabled).
  - SSO + provisioned users: SSO linkage (`sso_sub`) is used for integrating with identity-aware third-party apps; admin bulk-assign SSO flow helps align department ownership with external tooling.

- Notification toggles: each status option can be configured in the Admin UI to enable/disable notifications or limit them to cross-department transfers only. This prevents noisy emails for intra-department updates while ensuring handoffs create external tasks.

- Verification integrations: the verification service abstraction (`app/services/verification.py`) is pluggable — swap or extend with connectors that query internal ERP/parts DBs or external APIs and return structured verification results to the form renderer.

Integration guidance:

1. Decide whether external systems should be driven by emails, a ticketing API, or webhooks. Configure the corresponding settings and enable the `TICKETING_ENABLED` or webhook endpoint.
2. Use `StatusOption` (Admin → Status Options) to map statuses to `target_department` and control `notify_enabled` / `notify_on_transfer_only` behavior so only relevant transitions trigger external tasks.
3. Ensure SSO accounts are provisioned for users who should receive external task assignments; use the Admin SSO assign UI to align `User.department` and `sso_sub` values.
4. For verification, implement a connector under `app/services/verification.py` that reads env-configured endpoints/tokens and returns verification results used by the request forms.

These integration extension points are intentionally lightweight so you can build adapters (webhook forwarders, ticketing connectors, or direct API callers) without changing core workflow logic.

## Dev Notes
- Run `python3 seed.py` to seed sample data.
- Server entrypoint: `run.py` (Flask), Dockerfile provided; Fly configs included for deployment experiments.

## Local testing & new features

This project now includes an admin-managed "Special Emails" feature, an inbound-mail webhook, and a safe inventory integration skeleton. These are all optional and safe for prototype use — nothing is enabled by default.

- Admin UI: visit `/admin/special_emails` (admin only) to toggle the request-by-email feature, set the Help Email and Request Form Email, and edit the initial autoresponder message.

- Autoresponder: when enabled the app will send a reply to senders of the Request Form Email explaining how to submit requests by composing a subject line. The autoresponder uses the same EmailService used elsewhere (logs messages when `EMAIL_ENABLED` is false).

- Inbound mail webhook: a signed endpoint is available at `/integrations/inbound-mail` (CSRF-exempt). It expects a HMAC-SHA256 signature in the `X-Webhook-Signature` header. Example (bash):

```bash
# Replace these values for local testing
export WEBHOOK_SHARED_SECRET=your_test_secret
payload='{"from":"tester@example.com","subject":"title=Test;donor_part_number=ABC123"}'
sig=$(printf "%s" "$payload" | openssl dgst -sha256 -hmac "$WEBHOOK_SHARED_SECRET" | sed 's/^.* //')

curl -v \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: $sig" \
  -d "$payload" \
  http://localhost:8080/integrations/inbound-mail
```

The handler will parse semicolon-separated `key=value` pairs from the subject and (optionally) call the `InventoryService` to validate part numbers or sales list numbers. By default `InventoryService` is disabled and returns `null`/`None` for checks.

- Inventory skeleton: configuration keys are `INVENTORY_ENABLED` and `INVENTORY_DSN`. The implementation lives at `app/services/inventory.py`. When `INVENTORY_ENABLED` is false the service is a no-op, so current behavior is unchanged. To integrate later, implement `_client` using your DSN and return True/False from `validate_part_number()` / `validate_sales_list_number()`.

### Migrations / Alembic notes

Two migration files for the new `special_email_config` table are included under `migrations/versions/`:

- `0006_add_special_email_config.py` (hand-crafted)
- `0007_autogen_add_special_email_config.py` (autogenerate-style)

Do not run both of these in the same release sequence — they'll attempt to create the same table twice and conflict. Recommended options:

- Development/autogenerate workflow (preferred): install Alembic/Flask-Migrate, remove or ignore `0006_*`, then run `alembic upgrade head` (or `flask db upgrade`) to apply the autogen migration.
- Handcrafted workflow: keep `0006_*` and do not run `0007_*`; run `alembic upgrade head` (or use `db.create_all()` for local dev convenience).

Quick local steps to test everything without altering remote deployments:

```bash
# create & activate venv, install deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install alembic Flask-Migrate  # optional for migrations

# Option A: fast local (convenience)
export AUTO_CREATE_DB=true
python3 run.py

# Option B: apply Alembic migrations locally (recommended if using migrations)
export FLASK_APP=run.py
flask db upgrade      # or: alembic upgrade head
python3 run.py
```

### Trigger autoresponder manually (dev)

You can trigger the autoresponder from a Flask shell for testing:

```bash
python3 - <<'PY'
from app import create_app
with create_app().app_context():
    from app.notifcations import send_request_form_autoresponder
    send_request_form_autoresponder('you@example.com')
    print('Queued autoresponder')
PY
```

If you'd like, I can delete the handcrafted migration or the autogen file and then run `alembic upgrade head` here locally; tell me which migration you prefer to keep and I'll apply it and update the README accordingly.

Dev-only smoke-test scripts
- Smoke-test helper scripts (creating sample requests, populating UI buckets, and a webhook sender) have been moved out of the main `scripts/` folder and restored on a dedicated branch and folder: `dev-scripts/` on the `dev-scripts` branch. This keeps `main` clean for deployments.
- To use them locally, either check out the `dev-scripts` branch or copy the `dev-scripts/` folder into your working tree:

```bash
# checkout the branch containing dev helpers
git fetch origin dev-scripts:dev-scripts
git checkout dev-scripts

# or copy files into your current branch
git checkout main
git restore --source=origin/dev-scripts --worktree --staged -- dev-scripts
```

Use these scripts only for local development and testing; they are intentionally not present on `main` to avoid accidental population of production databases.

Inline target setting & donor edit rules
- Dept B dashboard now supports a quick inline "Set target" control for requests where a part-number artifact exists but the target is empty. When a target is set from the dashboard the app records the change and sends an in-app/email notification to the department currently owning the request (`owner_department`).
- Dept A may only edit a submitted donor part number when Dept B has explicitly requested an edit (the `edit_requested` flag). This prevents accidental overwrites; Dept B can edit part-number artifacts directly from their UI.

- When any department requests an artifact edit (via the request-edit control), the app records an audit entry and sends an in-app/email notification to the department that owns the artifact so the request is visible to the right people. Dept A will see an edit form only after such a request.

Debugging: interactive mini-window and debug workspace
- The Admin Monitor now includes an interactive "mini-window" that loads any internal path (for example `/dashboard`, `/requests/123`) inside an iframe for quick debugging. Controls: `Load`, `Refresh`, `Open in new tab`, `Open Debug Workspace`.
- The "Open Debug Workspace" opens a dedicated debug page at `/admin/debug_workspace?path=...` that embeds the requested internal path and shows guidance. Note: the debug workspace uses the same browser session and database as your current admin session — to get true session isolation, open the debug workspace in a Private/Incognito window or use a separate browser profile.

Quick use:
```bash
# In Admin Monitor choose a department (e.g. /admin/monitor?dept=B), then:
# - Enter an internal path in the mini-window input (e.g. /requests/1)
# - Click Load to render it inside the mini-window iframe
# - Click Open Debug Workspace to open the same path in a dedicated debug page (recommended to open in Private/Incognito for isolation)
```

## Migrations, Background Workers, and Docker Compose

This section summarizes the recommended steps for managing schema migrations,
background job processing (RQ), and running the application with Docker Compose.

- Install developer dependencies (local):

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

- Flask-Migrate / Alembic (generate migrations locally):

```bash
export FLASK_APP=run.py
# initialize migrations (only once)
flask db init
# autogenerate a migration from the models
flask db migrate -m "initial models"
# apply to an empty DB
flask db upgrade
# if your target DB already has the schema (production), mark it without DDL:
flask db stamp head
```

- RQ (Redis Queue) worker (for background email/ticketing tasks):

Set `RQ_ENABLED=1` and `REDIS_URL` to enable the RQ enqueue path. Start a worker locally with:

```bash
REDIS_URL=redis://localhost:6379 RQ_ENABLED=1 python3 scripts/rq_worker.py
```

- Docker Compose (development):

We include `docker-compose.yml` that starts `web`, `worker`, `db` (Postgres) and `redis` services.

```bash
docker compose up --build
# Generate migrations inside the `web` container (example):
docker compose run --rm web flask db migrate -m "initial models"
docker compose run --rm web flask db upgrade
```

## Seeding test users

To populate the database with sample users and requests for testing, you can run the included `seed.py` script.

Locally (recommended for development):

```bash
# Point to your dev or staging database, then run the seeder
export DATABASE_URL='sqlite:///instance/app.db'
PYTHONPATH=. python3 seed.py
```

On Fly (run inside the deployed container):

1. Ensure the app's `DATABASE_URL` secret points to a writable database and that the app machines are running.
2. Run the seed script on a live machine:

```bash
flyctl ssh console -a process-management-prototype-lingering-bush-6175 --command "cd /app && python3 seed.py"
```

Or open an interactive shell and run it manually:

```bash
flyctl ssh console -a process-management-prototype-lingering-bush-6175
cd /app
python3 seed.py
```

Notes:
- Running the seed on a production database will create test users and sample data — use a staging DB if you don't want test data in production.
- If you prefer not to SSH into the machine, run `seed.py` locally against the remote DB by exporting `DATABASE_URL` and running the script from your workstation.


Notes:
- The repository contains a minimal `migrations/` scaffold with an empty `0001_initial.py` that
  you can stamp as head if your DB already matches the models; prefer generating and reviewing
  migrations in the environment that matches your target DB (SQLite vs Postgres differences).
  
  Note: a recent change introduced a per-user `vibe_index` column to persist the UI "vibe" (theme)
  preference. An Alembic revision has been added at `migrations/versions/0005_add_vibe_index.py`.

  - To apply the migration with Alembic/Flask-Migrate:

  ```bash
  export FLASK_APP=run.py
  flask db upgrade
  ```

  - If you need a quick one-off fix for a local SQLite DB (dev), run:

  ```bash
  sqlite3 instance/app.db "ALTER TABLE user ADD COLUMN vibe_index INTEGER DEFAULT 0;"
  ```
- RQ is optional; the app falls back to a safe thread-based sender when RQ is not enabled.
- For production, replace the thread fallback with a reliable worker process (RQ/Celery) and
  ensure migrations are part of your deployment pipeline.

## CSRF, AJAX, and Webhooks

The app enables CSRF protection globally. For standard form POSTs the templates include the
CSRF token via `{{ form.hidden_tag() }}` or `{{ csrf_token() }}`. For JavaScript-driven
requests (fetch/XHR) the app exposes the token in a meta tag in `base.html`:

```html
<meta name="csrf-token" content="{{ csrf_token() }}">
```

The shipped `app/static/app.js` includes a small fetch wrapper that automatically adds the
`X-CSRFToken` header for non-GET requests so client-side code doesn't need to manually
attach the token.

If you need to accept external webhooks or anonymous POSTs (for example, third-party
services), avoid disabling CSRF globally. Instead either:

- Exempt only the specific route(s) from CSRF protection using `csrf.exempt` and validate the
  payload via a shared secret or signature header, or
- Require a pre-shared HMAC signature/header from the sender and verify it server-side before
  accepting the payload.

Document any exemptions in your deployment notes so reviewers understand the security trade-offs.

## Known Gaps
- No Alembic migrations; schema auto-creates in dev.
- Guest detail page surfaces public submissions/comments only; internal notes stay hidden.
- Placeholder verification endpoint (routes) still needs real lookup logic.

## Local DB migrations (development)

Small schema fixes for local development are provided in `migrations/`. The helper
script `migrations/apply_local_sqlite_migrations.py` will locate the configured
SQLite DB (from `config.py`), add missing columns, and recreate `audit_log` when
necessary so `request_id` can be NULL for system-level audit entries (for example
when an admin starts/stops impersonation).

Run the helper from the project root:

```bash
# Ensure the project root is on PYTHONPATH so config imports resolve
PYTHONPATH=. python3 migrations/apply_local_sqlite_migrations.py
```

If you'd rather recreate a clean dev DB instead of patching in-place, remove the
local DB file (commonly `instance/app.db` or `app.db` depending on config) and run:

```bash
python3 seed.py
```

Note: `app/metrics.py` attempts to import `prometheus_client`. If that package is
not installed the app uses a safe noop fallback; to enable Prometheus metrics run:

```bash
pip install prometheus_client
```

## Presentation / Deployment Notes

- Fix applied: password hashing now uses a compatible method (`pbkdf2:sha256`) to avoid runtime failures on platforms missing `hashlib.scrypt`.
- Remote helper: `scripts/remote_create_tables.py` can be run inside a deployed container to create DB tables when using SQLite (example: `flyctl ssh console -a <app> --command "python3 /app/scripts/remote_create_tables.py"`).
- Seeding: the demo data is seeded with `seed.py`. For the live demo the following accounts were created:
  - `a@example.com` / `password123` (Dept A)
  - `b@example.com` / `password123` (Dept B)
  - `c@example.com` / `password123` (Dept C)
  - `admin@example.com` / `admin123` (admin)

- Recommended demo flow:
  1. Visit the deployed app URL.
  2. Sign in as `a@example.com` to show Dept A views.
  3. Use `admin@example.com` to open the Admin Monitor and demonstrate impersonation / department switching.

Note: For production use a managed Postgres instance and run migrations via Alembic/Flask-Migrate; avoid relying on `AUTO_CREATE_DB` in production.

- Policy change (assignment): Department A users may no longer self-assign a request until Department B has processed it and explicitly sent it back to Department A. This enforces the demo workflow where Dept B handles initial review/work and returns the request to Dept A before A can claim it.
 - Startup safety: the container entrypoint now ensures DB tables exist on boot by running `scripts/remote_create_tables.py` unless `AUTO_CREATE_DB=0` is set. This prevents early requests (login, dashboard) from triggering a 500 when the SQLite DB file exists but tables are not yet created. You can still opt out by setting `AUTO_CREATE_DB=0` in your deployment environment.
 - Form behavior: when submitting a request with `Request Type = Both`, the `Target Part Number` field is now optional on both the guest request form and the Dept A/internal request form. The `Target` is still required when `Request Type = Method` (`instructions`).
