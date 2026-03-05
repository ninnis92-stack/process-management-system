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

If you prefer not to use Flask-Migrate, you can apply the SQL directly for SQLite:

```bash
sqlite3 instance/dev.sqlite3 "ALTER TABLE user ADD COLUMN is_admin INTEGER DEFAULT 0;"

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

## Search & Filtering
- Search endpoint `/search` (title/description/id) scoped by department access.
- Dept B dashboard shows status buckets and semantic filters (in progress, C review, final review, etc.). Closed items >24h are hidden.

## Nudges
- Only the original submitter can nudge; gated to 48h after creation and 24h cooldown; Dept C cannot send nudges.

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

## Dev Notes
- Run `python3 seed.py` to seed sample data.
- Server entrypoint: `run.py` (Flask), Dockerfile provided; Fly/Vercel configs included for deployment experiments.

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
