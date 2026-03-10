# Process Management Prototype

This repository contains a **Flask-based process management system** built as a prototype for handling
structured intake forms, multi‑step process flows, and departmental collaboration.  It is intended to
serve as the reference implementation for a larger process‑management platform, with a focus on:

- rapid configuration via templated request forms
- flexible verification and pre‑fill integrations (ERP, part lookup, etc.)
- rich admin tooling with feature flags, themes, and impersonation
- guest submission and tracking without requiring an account
- pluggable OCR and background job support
- camera-based field capture with MediaDevices API and lightweight OCR endpoint (``/verify/camera``); the client may specify which form field it expects and the server echoes that field name back so any input can be filled automatically; demo button on settings page exercises this functionality
- simple deployment on Postgres/Redis-hosting platforms such as Fly.io or Docker Compose

The codebase prioritizes readability and test coverage; it uses Flask for request handling, SQLAlchemy
for ORM, and RQ for asynchronous workers.  The front end remains mostly server-rendered with
lightweight Stimulus controllers for interactivity.

---

## Overview

*Note: recent updates changed dark-mode behavior such that enabling dark mode disables personal vibe/theme controls. The navbar vibe button is removed and the theme selector is greyed out with a warning, but adopted brand presets now carry their accent palette into the app's native dark mode automatically. The navbar banner now keeps quotes in their own panel, with the vibe button rendered inside its own solid control shell so it stays visually separate and can disappear cleanly when disabled. If the global vibe feature toggle is turned off, the shell is removed while the quote banner remains in a quote-only layout. Shared action-shell styling is now used across the navbar, command center, and monitor views so controls can appear or disappear without breaking alignment. The old dark-mode-compatible subset preview UI was also removed so dark mode has a single, consistent presentation, and the broader dashboard/admin/login surfaces now use a cleaner solid-panel visual system instead of the older glassy treatment. Recent dashboard polish also toned down the launchpad accents so the Workspace overview eyebrow, badges, and queue counters now follow the same quieter theme language as surrounding cards rather than using a separate bright-blue treatment.*

This prototype supports structured intake forms, multi‑step process flows, and an
extensible admin interface.  Admins can build custom request templates,
configure verification integrations that auto‑fill other fields, and declare
conditional requirements (per field, section, or upload area).  The app runs
on Postgres and optionally Redis, and is deployed on Fly.io with health checks
and release‑time schema safety.

Key capabilities:

- **Dynamic request templates** with sections, verification‑prefill, and
  conditional requirements
- **Clearer public entry flow** with a simplified guest intake path, no
  public department-switch modal, and the default quote set used on the
  login screen when rotating quotes are enabled
- **Process-flow engine** with status transitions, path history and loop protection
- **Priority and reminder controls** including `highest` priority, automated
  reminders, user-pushed reminders, and per-user daily reminder limits
- **Handoff operations tooling** with department-level default handoff docs and
  checklists, temporary cross-department coverage, coverage calendar search,
  and downloadable `.ics` exports
- **Scalable notifications** with department-specific templates, backup
  approver routing, admin-monitored department filtering, a dedicated
  in-app notifications page, and async fan-out for larger recipient groups
- **Polished public sign-in** with clearer guest-path entry points and a more
  production-ready first impression for external users
- **Command center** for users, departments, process flows, site config, integrations,
  guest request forms, feature flags, and more
- **Smarter navigation**: the client adds prefetch hints for hovered links so
  subsequent clicks feel faster without requiring any backend changes.
- **Field verification** powered by third‑party tracker integrations
- **Optional handoff bundle delivery** through existing ticketing/webhook
  integrations so transfer packets can be mirrored externally without adding
  more core workflow form fields
- **Guest submission and lookup** via external blueprints
- **Guest access controls** so admins can independently turn guest lookup
  pages and guest submission pages on or off from feature flags
- **Per-form guest access policies** for public, SSO-linked, approved-organization,
  and unaffiliated-only intake paths
- **Cleaner GitHub automation** with repaired CI/deploy workflows and a valid
  Codespaces prebuild workflow configuration
- **SSO/OIDC support** with optional admin sync
- **Theme/vibe system**, dark mode (now integrated with vibe accents) and explicit no‑vibe support. Dark mode disables personal vibe overrides and hides the vibe button, while adopted brand presets continue to tint the native dark palette so imported branding still looks natural. Importing branding from a website now suppresses the rolling-quote banner and locks accent/vibe controls; when the global vibe feature is turned off the UI switches to a unique neutral palette with its own slate‑toned accents rather than lingering on the last selected color. The theme dropdown is locked with explanatory text shown to the user, and the names of the built-in presets have been updated to match the softer accent palette: *Sky*, *Moss*, *Dawn*, and *Twilight* (replacing Ocean/Forest/Sunset/Midnight respectively). The navbar quote area and vibe control are separated so quotes stay visible even when the vibe button is absent, the vibe button itself now sits inside a distinct solid control shell instead of blending into the banner, shared action bars and control shells keep admin and monitor layouts uniform when controls are added or removed, and the quote slot now clamps long lines on desktop while still exposing the full text via tooltip/ARIA. A recent set of fixes ensures the brand title never gets obscured by the quote/vibe banner, adds extra spacing when the banner wraps on narrow screens, and increases the left gap to prevent the last letter from touching the banner border. The login page now uses the shared `surface-panel`/`form-shell` layout and page header, delivering the same look and feel as the rest of the app. Recent UI polish also darkened the lighter preset accents so theme-controlled buttons and labels remain readable, replaced the older glassy treatment with a more solid shared surface system across login, dashboard, settings, and admin pages, and kept dashboard overview/badge accents aligned with surrounding cards instead of using an unrelated bright-blue emphasis. Preferences, feature flags, and other toggle/dropdown controls save instantly without any "Save" button

Everything is covered by a comprehensive test suite and deploys automatically
using a release script that migrates the database, creates missing columns,
seeds baseline accounts, and backfills recent guest-form schema additions when
needed. Repository diff noise is also reduced with `.gitattributes`, which
hides generated assets and vendored dependencies from GitHub language stats
and default diff views.

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

  Preferences and feature flags now autosave as soon as you change them; the page will post JSON to the server and even flush outstanding requests on navigation via the `keepalive` API.  Dropdowns (vibe/theme selector, quote set, etc.) are treated the same way, and the server echoes back the current value so the UI stays in sync.

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
   default unless `RUN_SEED_ON_RELEASE=0`.  For Fly.io deployments the
   `release_command` in `fly.toml` invokes the same script, so the remote
   database is automatically migrated and seeded each time you `fly deploy`.
  For faster workspace provisioning you can also bootstrap a tenant and its
  initial admin with `flask onboard-tenant --slug <slug> --name <name> --admin-email <email>`
  or the wrapper script `python scripts/onboard_tenant.py ...`.
   Run `python seed.py` locally if you need to resynchronize a development
   database or inspect the seeding logic.  The release script now also
   normalizes and validates quote sets so every built-in set has loadable
  content before a deploy is considered healthy. Recent release safety nets
  also backfill the newer department notification-template and handoff-default
  columns so older installs can deploy without manual SQL.

4. **Run the app (local deployment)**
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
   When you push to Fly, the deploy output will list a URL; once testing shows
   the root redirecting to `/dashboard` and `/dashboard` redirecting to
   `/auth/login` the release has succeeded.  A subsequent `fly ssh console` and
   `python seed.py` may be run if you need to reseed the remote database for
   diagnostics.

5. **Smoke testing**
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
  make test         # run pytest suite (currently 231 tests)
   ```

6. **Clearing state**
   - In dev, simply delete the SQLite file under `instance/app.db` or remove Docker volumes.
   - For production, use `flask db downgrade base` or `python scripts/clear_db.py` (not included) to
     reset.  The `flask clear-open-requests` CLI command can close all active work items.

7. **Deployment & smoke workflow**
   After you've pushed changes to `main` and are ready to deploy, the repository provides
  a helper that runs tests, pushes your branch, and triggers a Fly.io deployment:
   ```bash
   make deploy-safe       # runs tests, git push, and flyctl deploy
   ```
   Set `FLY_APP` in your environment or `fly.toml` if not already configured.

   Once the new release is live, run the basic smoke script against the target URL:
   ```bash
  bash scripts/smoke_test.sh https://your-app.fly.dev
  python scripts/smoke_deployed_login.py --url https://your-app.fly.dev
  python scripts/admin_smoke.py --url https://your-app.fly.dev
   ```
   For staging environments the `scripts/clear_smoke_remote.py` helper logs in as the
   seeded admin and posts to `/admin/debug/cleanup` to remove test records:
   ```bash
   python scripts/clear_smoke_remote.py --url https://your-app.fly.dev
   ```
   These steps are also documented in `docs/STAGING.md` under the existing checklist.

   When hosting locally you can still exercise everything with `make run` and
   `make smoke`/`make smoke-clean` as described above.  The `make deploy` target
   simply does `git push` and `flyctl deploy -a $(FLY_APP)`.

8. **Tests**
   ```bash
  make test          # runs full pytest suite (currently 231 tests)
  make test-postgres # start a temporary Postgres container and run the suite against it
   ```

   The GitHub Actions pipeline now includes a `postgres-test` job which spins up
   Postgres 15 as a service and runs the same tests, ensuring dialect
   compatibility.

9. **Performance & tuning**

   This is a prototype but there are a few built‑in helpers and some
   documentation if you start exercising it under load:

   * see `docs/PROFILING.md` for a longer checklist on profiling, eager‑loading
     relationships, pagination, and caching; the note at the bottom of that
     file even contains a sample query showing `selectinload()` usage when you
     need to avoid N+1 database round‑trips.
   * the application already caches the dashboard, search results, and
     metrics UI for a short time; templates use request-scoped caches in
     helpers such as `get_user_departments()` and `gravatar_url()` to avoid
     repeating identical database or hashing work within a single request
     without leaking stale values across requests.
   * performing a `make smoke` run or using `k6/load_test.js` while running a
     profiler (e.g. `pyinstrument`) is the best way to identify the real
     hotspots in your usage scenario.  Once you know where the delays are you
     can apply any of the tactics listed earlier: eager loads, Redis or
     lru_cache decorators, background jobs, database indexes, etc.

   A “finish‑the‑job for you” implementation of all of the bullet points
   listed earlier would require a detailed audit of every handler and model;
   the repository provides the tools to make that audit easy, but it isn’t the
   sort of change you can auto‑generate with a single patch.  Start by
   measuring, optimize a few hot code paths, and iterate.  

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
- Release-time schema repair also backfills newer department/user handoff and
  notification columns used by coverage planning, notification templating, and
  handoff package defaults.
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
admin site config for quick sanity checks against any environment.  You can
also `curl -i https://<app>/ready` to validate the readiness probe (database
connection plus optional Redis).  After a Fly deployment the smoke test
should return a 302 from `/` and a 302 to `/auth/login` from `/dashboard`.

If you ever need to reseed or inspect the remote database, use SSH to run
the same `seed.py` script that the release command executes:

```bash
fly ssh console --command "python seed.py"
```

The output will confirm which demo users and quote sets exist, and the
script will automatically apply any missing columns before creating data.  
This is handy for debugging or bringing a recently created app up to speed
with the local development schema.

Webhook smoke script (`scripts/webhook_smoke.py`) verifies that production
webhooks reject unsigned traffic and, when a shared secret is supplied,
accept a correctly signed payload for `/integrations/incoming-webhook`.

Use `python scripts/verify_quote_sets.py` to inspect and normalize stored quote
sets manually; the command exits non-zero if any quote set still lacks content.

### Reminder and priority controls

- Automated reminders can be enabled from the admin feature flags and special
  email settings screens.
- Reminder cadence now supports status-driven escalation: hourly, every 4
  hours, or once per day.
- Admins can assign each user a daily reminder allowance from 1 to 5.
- Signed-in users can push manual reminders when that feature flag is enabled.
- Public login now surfaces direct guest dashboard and guest submit actions so
  external users do not need to guess which path applies to them.
- Requests support four priority tiers: `low`, `medium`, `high`, and `highest`.
- Admins and department heads with the `can_change_priority` permission can
  update request priority directly from the request detail workspace.

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

## Live deployment checks (March 8-9, 2026)
- March 10, 2026: fixed a dashboard bucket-query regression by batching
  `BucketStatus` lookups instead of eager-loading the dynamic relationship,
  made admin workflow-profile sync idempotent for `DepartmentEditor` rows,
  and moved helper caches to request scope so department-switch results stay
  fresh across requests in tests and production.
- Re-ran the full local regression suite after those fixes; it passed at
  `221 passed`.
- Added a progressive-disclosure process-flow builder, clearer guest/internal
  request-form previews, extracted guest-form admin routes into
  `app/admin/guest_forms.py`, and completed a terminology pass so process flow,
  request form, template, route, and department read as distinct concepts.
- Re-ran the expanded regression suite after the cleanup/refactor; it passed at
  `49 passed` for the admin command center, navigation, guest request forms,
  internal intake, and process-flow UI slices.
- Deployed the latest release to
  `process-management-prototype-lingering-bush-6175` with
  `fly deploy -a process-management-prototype-lingering-bush-6175`.
- Verified the Fly release command completed successfully, the updated machine
  reached `started`, and Fly health checks reported `/ready` with
  `components.database.status: ok`.
- Ran `fly ssh console --command "python seed.py"` against the live app and
  confirmed seeded users plus all quote sets were present at `30 quote(s)` each.
- Ran deployed smoke checks with:
  `bash scripts/smoke_test.sh https://process-management-prototype-lingering-bush-6175.fly.dev`,
  `python scripts/smoke_deployed_login.py --url https://process-management-prototype-lingering-bush-6175.fly.dev`,
  `python scripts/admin_smoke.py --url https://process-management-prototype-lingering-bush-6175.fly.dev`, and
  `python scripts/clear_smoke_remote.py --url https://process-management-prototype-lingering-bush-6175.fly.dev`.
- Verified seeded-user login, admin routes, metrics JSON, remote cleanup, and
  both `/health` and `/ready`; the live app and database are healthy.
- Polished the public sign-in experience with a stronger hero, direct guest
  entry points, and clearer production-facing copy; also introduced
  reminder-named aliases such as `notify-reminders`, `/push_reminder`, and
  `/admin_reminder` while keeping legacy compatibility paths intact.
- Re-ran the full local suite after the UX pass; it remained green at
  `161 passed`.
- Deployed the polish pass to `process-management-prototype-lingering-bush-6175`
  with `flyctl deploy -a process-management-prototype-lingering-bush-6175`.
- Verified the live login page now renders the new copy and CTAs including
  `Sign in to keep requests moving`, `Open Guest Dashboard`, and
  `Start Guest Submission`.
- Re-ran deployed smoke checks plus cleanup, then confirmed `/health` and
  `/ready` both returned `{"status":"ok"}` with the database healthy.
- Confirmed Fly logs again showed `Seeded users:`, `Quote sets:`, `seeded`,
  `quote_sets=ok total=11 active=default active_count=5`, and `db_ready`
  during the post-deploy boot path.
- Added department-head priority controls in the request workspace, completed
  the reminder wording pass, and documented the new reminder and `highest`
  priority flows; the local suite now passes with `161 passed`.
- Deployed to `process-management-prototype-lingering-bush-6175` with
  `flyctl deploy -a process-management-prototype-lingering-bush-6175`.
- Verified Fly release logs showed `schema_fix=user.daily_nudge_limit_added`,
  `schema_fix=department_editor.can_change_priority_added`,
  `schema_fix=status_option.nudge_level_added`, `Seeded users:`, `Quote sets:`,
  `seeded`, and `quote_sets=ok total=11 active=default active_count=5`,
  confirming `scripts/release_tasks.py` and `seed.py` ran successfully against
  the production database.
- Ran deployed smoke checks with `bash scripts/smoke_test.sh`,
  `python scripts/smoke_deployed_login.py`, `python scripts/admin_smoke.py`,
  and `python scripts/clear_smoke_remote.py`; seeded user login, admin routes,
  metrics, and remote cleanup all completed successfully.
- Checked `https://process-management-prototype-lingering-bush-6175.fly.dev/health`
  and `https://process-management-prototype-lingering-bush-6175.fly.dev/ready`;
  both returned `{"status":"ok"}`, and readiness confirmed the database was
  healthy.
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
(see `docs/MAINTAINER_NOTES.md` for a full changelog, deployment history, feature notes, and operational guidance)

---

## Feature notes

*(moved to docs/MAINTAINER_NOTES.md)*

mobile-friendly routing and access summaries on both the admin and submitter
screens.

Supported submitter access policies:

- `public` — anyone with the form link can submit
- `sso_linked` — the submitter email must belong to an existing SSO-linked user
- `approved_sso_domains` — the submitter must be SSO-linked and their email
  domain must match an approved organization domain configured on the form
- `unaffiliated_only` — blocks known affiliated/SSO-linked organization members
  so the form can be reserved for unaffiliated submitters

Each guest form (and any internally managed template) now allows an
**administrable layout** choice (`Standard`, `Compact`, or `Spacious`).
This setting drives a CSS class applied to the intake page and is also
returned by the `/api/templates` endpoint so third‑party clients can
mirror the same spacing and width when rendering external copies of a
form.  The layout is preserved when submissions from external providers
are mapped back into the application.

For connected third‑party forms, the app now also exposes a generated
schema endpoint at `/integrations/templates/<template_id>/external-schema`
(and the standalone API mirror at `/api/templates/<template_id>/external-schema`). That
response includes the connected template layout, section grouping, and
field specification so an external form builder can render a matching
experience. When the provider posts back to
`/integrations/external-form-callback`, payload fields are translated into
the connected template’s native field names before the request and
submission are created, so the data lands as if it had been entered in the
app itself. The in-app external form screen also links directly to the
generated schema so admins and integrators can verify the live contract and
confirm the visual layout (`Standard`, `Compact`, or `Spacious`) that the
third-party form should mirror.

**Notes on rolling quotes:** quotes shown in the navbar are selected
at random on every page render and during the automatic 8‑second rotation,
meaning there is no repeating, predictable cycle.  Each quote set shipped with
the app contains 30 entries, and shorter sets are expanded with themed
motivational filler lines instead of generic placeholders. The server-side rendering uses `random.choice` so the initial text
on each request is truly arbitrary.  The separate rolling-quote banner that
used to appear under the navbar has been removed entirely.
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

### Process-flow safety

Transition endpoints maintain a short‑term history of status moves and
prevent bouncing between the same two states repeatedly.  The request detail
page displays the last few steps and suggests next actions to the user.

---

## Admin & user interface

- **Command center**: located under `/admin` with subpages for users, departments,
  process flows, statuses, site configuration, integrations, feature flags, guest
  request forms, and request-form templates.
- Department admins can now store default handoff document links and checklist
  templates per department. Those defaults prefill temporary assignment cards,
  stay mobile-friendly in the admin UI, and flow into the coverage calendar and
  `.ics` export when a specific assignment does not override them.
- The coverage calendar now supports saved free-text search by teammate,
  department label, note, checklist item, handoff doc URL, or backup pair so
  larger organizations can narrow active coverage quickly without losing the
  existing lightweight workflow.
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
- Notification delivery now supports per-department body templates and can
  switch to async fan-out for larger recipient lists while still keeping in-app
  notifications and backup-approver routing intact during smaller day-to-day
  sends.
- Ticketing and webhook integrations can optionally emit a structured handoff
  bundle payload containing request metadata, submission details, and
  attachment descriptors whenever a department handoff is created.
- **User settings**: dark mode (keeps adopted brand presets blended into the native dark palette while disabling personal vibes), theme/vibe selection, quote set, rotating
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
personal vibe accents are suppressed in dark mode, adopted brand presets now
flow through the native dark palette, and raw external CSS themes still revert
to a basic compatible dark treatment.


---

Enjoy building and customizing your request process flows! Feedback and patches
are welcome via the GitHub repository.
