# Process Management Prototype

This repository contains a **Flask-based process management system** built as a prototype for handling
structured intake forms, multi‑step workflows, and departmental collaboration.  It is intended to
serve as the reference implementation for a larger process‑management platform, with a focus on:

- rapid configuration via templated request forms
- flexible verification and pre‑fill integrations (ERP, part lookup, etc.)
- rich admin tooling with feature flags, themes, and impersonation
- guest submission and tracking without requiring an account
- pluggable OCR and background job support
- simple deployment on Postgres/Redis-hosting platforms such as Fly.io or Docker Compose

The codebase prioritizes readability and test coverage; it uses Flask for request handling, SQLAlchemy
for ORM, and RQ for asynchronous workers.  The front end remains mostly server-rendered with
lightweight Stimulus controllers for interactivity.

---

## Overview

This prototype supports structured intake forms, multi‑step workflows, and an
extensible admin interface.  Admins can build custom request templates,
configure verification integrations that auto‑fill other fields, and declare
conditional requirements (per field, section, or upload area).  The app runs
on Postgres and optionally Redis, and is deployed on Fly.io with health checks
and release‑time schema safety.

Key capabilities:

- **Dynamic request templates** with sections, verification‑prefill, and
  conditional requirements
- **Workflow engine** with status transitions, path history and loop protection
- **Command center** for users, departments, workflows, site config, integrations,
  guest forms, feature flags, and more
- **Field verification** powered by third‑party tracker integrations
- **Guest submission and lookup** via external blueprints
- **Per-form guest access policies** for public, SSO-linked, approved-organization,
  and unaffiliated-only intake paths
- **SSO/OIDC support** with optional admin sync
- **Theme/vibe system**, dark mode (now integrated with vibe accents) and per‑user preferences

Everything is covered by a comprehensive test suite and deploys automatically
using a release script that migrates the database, creates missing columns,
seeds baseline accounts, and backfills recent guest-form schema additions when
needed.

---

## Getting started (development)

1. **Clone and prepare environment**
   ```bash
   git clone https://github.com/ninnis92-stack/process-management-system.git
   cd process-management-prototype
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

   The frontend uses npm/Vite for modern JS.  To install dependencies:
   ```bash
   cd frontend
   npm install      # or yarn
   ```
   During development run `npm run dev` and to produce a production bundle use `npm run build` (assets output to `app/static/dist`).

2. **Configure**
   Set environment variables or edit `config.py`.  Required:
   - `DATABASE_URL` (Postgres)
   - `SECRET_KEY` (Flask session)
   Optional:
   - `REDIS_URL` (if using Redis for caching/queues/health)
   - tracker tokens such as `ERP_VERIFY_TOKEN` for verification integrations

3. **Database setup**
   Use either:
   ```bash
   flask db upgrade            # run Alembic migrations
   # or, preferred for dev/production parity:
   python scripts/release_tasks.py   # migrations + safe ALTERs + seeds
   ```
   The release script will also seed demo users and an admin account by
  default unless `RUN_SEED_ON_RELEASE=0`. It now also normalizes and validates
  quote sets so every built-in set has loadable content before a deploy is
  considered healthy.

6. **Run the app (local deployment)**
   ```bash
   export FLASK_APP=run.py
   flask run
   ```
   By default it binds to `127.0.0.1:5000`.  To simulate a production environment you can
   use Docker Compose:
   ```bash
   docker-compose up --build
   ```
   which brings up Postgres, Redis, and the web container.  The same `Fly.toml` configuration
   in the repo can be used to deploy to Fly.io with `fly deploy`.

7. **Smoke testing**
   Once the server is running, verify the basics:
   - navigate to `/auth/login` and sign in with the seeded admin (`admin@example.com`/`password123`)
   - create a new request via the dashboard and confirm you can view/track it
   - upload an attachment and watch OCR text appear (requires Tesseract installed locally)
   - visit `/admin` and toggle a feature flag or create a quick guest form
   - note that the site banner feature has been removed; quotes now live only in
     the navbar and randomize daily rather than showing as a separate alert
   Automated helpers are available via Makefile:
   ```bash
   make smoke        # hit home, dashboard, and admin/site_config
   make smoke-clean  # erase local sqlite DB between runs
   make test         # run pytest suite (≈100 tests)
   ```

8. **Clearing state**
   - In dev, simply delete the SQLite file under `instance/app.db` or remove Docker volumes.
   - For production, use `flask db downgrade base` or `python scripts/clear_db.py` (not included) to
     reset.  The `flask clear-open-requests` CLI command can close all active work items.

5. **Tests**
   ```bash
   make test          # runs full pytest suite (≈100 tests)
   ```

---

## Database & migrations

- Models live in `app/models.py`; business logic is factored into service
  modules under `app/services/` (e.g. `request_creation.py`,
  `requirement_rules.py`).
- Migrations are managed with Alembic; the `scripts/release_tasks.py` helper
  applies them plus additional `ALTER TABLE` fixes to keep production and
  development schemas aligned.
- A second release‑time task creates missing columns safely and can seed the
  database on every deploy (controlled by `RUN_SEED_ON_RELEASE` env var).
- The same release path now also repairs legacy `guest_form` installs by adding
  `access_policy`, `allowed_email_domains`, and
  `credential_requirements_json` when those fields are missing.
- Release-time quote validation auto-fills missing built-in quote sets, resets an
  invalid active quote set back to `default`, and fails the release if any set
  would still be empty.
- Docker Compose includes healthchecks for Postgres and Redis, and `entrypoint.sh`
  waits for dependencies using `scripts/wait_for_redis_ready.py`.

---

## Health & readiness

Two endpoints exist:

- `/health` – simple liveness check, always returns 200 when the app is
  running.
- `/ready` – readiness probe that verifies the Postgres connection; also
  attempts to initialize Redis if `REDIS_URL` is set (otherwise skip).

Fly.io is configured (`fly.toml`) to use `/ready` for readiness.

Run `curl -i https://<app>/ready` to verify production readiness; you should
see JSON indicating `database.status:ok` (and Redis if configured).

Smoke test script (`scripts/smoke_test.sh`) hits the home page, dashboard and
admin site config for quick sanity checks against any environment.

Webhook smoke script (`scripts/webhook_smoke.py`) verifies that production
webhooks reject unsigned traffic and, when a shared secret is supplied,
accept a correctly signed payload for `/integrations/incoming-webhook`.

Use `python scripts/verify_quote_sets.py` to inspect and normalize stored quote
sets manually; the command exits non-zero if any quote set still lacks content.

### Quote permissions
Admins can restrict which named quote sets are available per department or on a
per-user basis. The site config UI exposes two JSON fields:

```json
{"A": ["default", "engineering"},
 "B": ["coffee-humour"]}
```

and

```json
{"user@example.com": ["productivity"]}
```

Department rules apply first; if a specific user email is listed, that list
replaces any department restriction. Admin users are exempt from these rules and
always see every configured quote set. When creating or editing a user the
admin form now includes controls for the initial `quote_set` and `quotes_enabled`
flag so assignments do not need to be POSTed manually.
> **Tip:** during the recent diagnostics cycle the code temporarily logged
> quote-context information at every `requests.dashboard` render to debug a
> regression; that logging has been removed from the default branch but the
> note remains here for historical context.
Prometheus scrape templates live under [ops/prometheus/fly-scrape.yml](ops/prometheus/fly-scrape.yml)
and a production monitoring runbook lives in [docs/MONITORING.md](docs/MONITORING.md).

---

## Deployment

- `make deploy-safe` builds, tests, and pushes the container to Fly.
- The image’s `entrypoint.sh` ensures databases are available and optionally
  seeds on boot (`SEED_ON_BOOT`, default `1`).
- GitHub Actions now includes a scheduled production monitoring workflow that
  runs health checks, seeded-user login, admin smoke, signed webhook smoke,
  and cleanup against Fly.
- Fly secrets to set:
  `SECRET_KEY`, `DATABASE_URL`, `SESSION_COOKIE_SECURE=True`,
  `PREFERRED_URL_SCHEME=https`, and any tracker auth tokens.
- Optional but recommended monitoring/alerting secrets:
  `SENTRY_DSN`, `SENTRY_ENVIRONMENT=production`, `WEBHOOK_SHARED_SECRET`,
  `PAGERDUTY_ROUTING_KEY`, `PRODUCTION_BASE_URL`, `PRODUCTION_ADMIN_EMAIL`,
  and `PRODUCTION_ADMIN_PASSWORD`.

> **Feature flag defaults:** flags are stored in the database and may initially
> contain `NULL` values.  The application now treats `None` as a sensible
> default (e.g. `rolling_quotes_enabled` defaults to `True`) instead of
> disabling the feature.  This avoids an empty row accidentally turning off key
> functionality during an upgrade; missing values are normalized during every
> release task run.

- Redis is optional; if you set `REDIS_URL` Fly health will check it, otherwise
  it’s skipped.

### Live deployment checks (March 8, 2026)
- Added production monitoring assets: `sentry-sdk` support in dependencies,
  a Prometheus scrape template, a scheduled GitHub Actions monitor, a PagerDuty
  notifier, and a signed webhook smoke script for production-only webhook paths.
- Added production-path regression coverage for SSO fallback/no-email behavior,
  webhook replay rejection, inbound-mail signature rejection, and health probes;
  the local suite now passes with `149 passed` after this hardening pass.
- Deployed to `process-management-prototype-lingering-bush-6175` with `flyctl deploy -a process-management-prototype-lingering-bush-6175`.
- Verified Fly release logs again showed `seeded`, `Seeded users:`, `Quote sets:`,
  and `quote_sets=ok total=11 active=default active_count=5`, confirming `seed.py`
  ran and the Fly database converged during release.
- Ran deployed smoke checks with `bash scripts/smoke_test.sh`,
  `python scripts/smoke_deployed_login.py`, `python scripts/admin_smoke.py`,
  and `python scripts/clear_smoke_remote.py`; health, seeded login, admin pages,
  metrics, and cleanup all completed successfully.
- Checked `https://process-management-prototype-lingering-bush-6175.fly.dev/health`
  and `https://process-management-prototype-lingering-bush-6175.fly.dev/ready`;
  both returned `{"status":"ok"}`, and readiness reported the database healthy.
- Added dedicated release-task regression coverage for quote-set normalization and invalid active-set repair; the local suite now passes with `122 passed`.
- Deployed to `process-management-prototype-lingering-bush-6175` with `flyctl deploy -a process-management-prototype-lingering-bush-6175`.
- Verified Fly release logs showed `Seeded users:`, `Quote sets:`, `seeded`, and `quote_sets=ok total=11 active=default active_count=5`, confirming `seed.py` ran and quote validation completed during release.
- Ran deployed smoke checks with `bash scripts/smoke_test.sh https://process-management-prototype-lingering-bush-6175.fly.dev`, `python scripts/smoke_deployed_login.py --url https://process-management-prototype-lingering-bush-6175.fly.dev`, and `python scripts/admin_smoke.py`; seeded user and admin logins both succeeded and the checked admin/metrics routes returned HTTP 200.
- Cleared remote smoke data with `python scripts/clear_smoke_remote.py`; the cleanup endpoint completed successfully and reported `{"deleted":0}`.
- Checked both `https://process-management-prototype-lingering-bush-6175.fly.dev/ready` and `https://process-management-prototype-lingering-bush-6175.fly.dev/health`; both returned `{"status":"ok"}`, and `/ready` reported `components.database.status: ok`.
- Added regression coverage for the hero dashboard CTA so guest and authenticated views keep the correct labels and target URLs; the local suite now passes with `115 passed`.
- Deployed to `process-management-prototype-lingering-bush-6175` with `flyctl deploy -a process-management-prototype-lingering-bush-6175`.
- Verified the Fly release command `python scripts/release_tasks.py` completed successfully and that release/boot logs showed `seed.py` running plus the seeded demo/admin accounts being emitted.
- Added a release-task schema safety net for legacy `form_template` installs, and confirmed Fly applied `schema_fix=form_template.external_enabled_added`, `schema_fix=form_template.external_provider_added`, `schema_fix=form_template.external_form_url_added`, and `schema_fix=form_template.external_form_id_added` during deploy.
- Ran deployed smoke checks with `bash scripts/smoke_test.sh https://process-management-prototype-lingering-bush-6175.fly.dev`, `python scripts/smoke_deployed_login.py --url https://process-management-prototype-lingering-bush-6175.fly.dev`, and `python scripts/admin_smoke.py`; after the schema fix the admin assignments page returned HTTP 200.
- Cleared remote smoke data with `python scripts/clear_smoke_remote.py`; the cleanup endpoint completed successfully and reported `{"deleted":0}`.
- Checked both `https://process-management-prototype-lingering-bush-6175.fly.dev/ready` and `https://process-management-prototype-lingering-bush-6175.fly.dev/health`; both returned `{"status":"ok"}`, and `/ready` reported `components.database.status: ok`.
- The login page now uses the `motivational` quote set when rolling quotes are enabled; admins can toggle the flag on or off via `/admin/feature_flags` and the control is independent of any per-user preferences.
- Added client‑side persistence for toggle checkboxes (feature flags and similar forms), ensuring their on/off state survives page refreshes after saving.

---

## Feature notes

### Guest forms and external intake

Guest forms can now be configured per form from the admin UI with clearer,
mobile-friendly routing and access summaries on both the admin and submitter
screens.

Supported submitter access policies:

- `public` — anyone with the form link can submit
- `sso_linked` — the submitter email must belong to an existing SSO-linked user
- `approved_sso_domains` — the submitter must be SSO-linked and their email
  domain must match an approved organization domain configured on the form
- `unaffiliated_only` — blocks known affiliated/SSO-linked organization members
  so the form can be reserved for unaffiliated submitters

**Notes on rolling quotes:** the quotes shown in the navbar are now randomized
once per day using a deterministic seed; the server picks the initial quote using
the same algorithm so the page loads with the correct text.  The separate
rolling-quote banner that used to appear under the navbar has been removed
entirely.
Additional notes:

- Approved organization domains are stored as a newline- or comma-separated list
  and normalized to lowercase.
- Each guest form also stores `credential_requirements_json`, which is not yet
  enforced at runtime but is reserved for future SSO claim / credential
  requirement integrations.
- Legacy installs that only used `require_sso` remain compatible: forms without
  an explicit `access_policy` fall back to the old behavior automatically.

### Request templates

Admin can create templates that:

- Group fields into named sections
- Declare verification rules that can auto‑fill other fields
- Enable a toggle for verification‑prefill per template
- Define conditional requirement rules with a UI builder or raw JSON

The UI shows badges for verified/required/auto-fill fields and tracks section
completion.  JavaScript provides live hints when requirements activate.

### Verification & prefills

A field’s verification rule may specify `prefill_targets`; when the source
field verifies (client‑side or server‑side) the system will attempt to populate
those targets.  This works both in-browser and during submission validation.

### Conditional requirements

Rules can reference other fields or entire sections. Operators include
`populated`, `equals`, `one_of`, `verified`, `any_populated`, and
`all_populated`.  Admins edit rules via a guided builder on the field settings
page; advanced users can edit the underlying JSON.

### Workflow safety

Transition endpoints maintain a short‑term history of status moves and
prevent bouncing between the same two states repeatedly.  The request detail
page displays the last few steps and suggests next actions to the user.

---

## Admin & user interface

- **Command center**: located under `/admin` with subpages for users, departments,
  workflows, statuses, site configuration, integrations, feature flags, guest
  form templates, etc.
- Admin users no longer see the department‑selection prompt on every page
  refresh.  The modal only appears when they intentionally choose “Switch
  Dept” (this makes the command center experience smoother on phones and other
  devices where the previous automatic picker was distracting).  The navbar
  picker now uses the same POST `/auth/switch_dept` endpoint as the regular
  multi‑department control, ensuring the chosen department is stored in the
  session and persists across views.
- Non‑admin users who belong to multiple departments now see a permanent
  dropdown picker in the top‑nav bar.  It functions exactly like the admin
  selector but updates the session via a simple POST to `/auth/switch_dept`.
  Because the dropdown is always present, the automatic choose‑department
  modal is suppressed (the UI still includes the page but it only opens if the
  user deliberately navigates there).  This avoids annoying popups on mobile
  while keeping department switching quick and obvious.
- Rolling quotes are seeded and normalized on every deployment; the release
  command logs `quote_sets=ok` and authenticated pages include a
  `#rolling-quotes-data` script tag when quotes are enabled.  To avoid the
  placeholder <code>Loading inspiration…</code> appearing if the client-side
  script fails, the server now injects the first quote directly into the HTML
  and the JavaScript falls back to a built-in list when a configured set is
  empty.  Smoke tests and unit tests verify the banner text appears.
- Administrators can restrict available quote sets by department or by
  individual user via the site configuration page.  When both a department and
  user rule exist the user-specific list wins; admins themselves bypass these
  restrictions and always have access to every defined set for testing and
  configuration purposes.  The quote-selection dropdown in user settings and
  admin forms only shows the allowed names.
- Stored per-user preferences are normalized to lowercase/trimmed values on
  save and during seed/release tasks, protecting against case mismatches or
  legacy entries that could otherwise disappear after an upgrade.
- **User settings**: dark mode (tints with the chosen vibe), theme/vibe selection, quote set, rotating
  quotes.
- **Templates & requirements**: rich form editing with grouped fields, hints,
  and other metadata.
- Shared UI macros (`app/templates/admin/_macros.html`) keep styles consistent.

Documentation for internal architecture and UI patterns lives in the `docs/`
folder.

---

## Changelog

All notable changes are tracked in git history; refer to commit messages for
more detail.  Recent updates include schema fixes, health checks, seeding
behavior, admin‑template/requirement engine, and a redesign of dark mode:
when vibe/theming is active the dark UI now inherits accent colors, while
external/imported themes will revert to a basic, compatible dark palette.


---

Enjoy building and customizing your request workflows! Feedback and patches
are welcome via the GitHub repository.
