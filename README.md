# Process Management Prototype

A lightweight, Flask‑based request tracking application designed for cross‑department workflows.

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
- **Admin console** for users, departments, workflows, site config, integrations,
  guest forms, feature flags, and more
- **Field verification** powered by third‑party tracker integrations
- **Guest submission and lookup** via external blueprints
- **SSO/OIDC support** with optional admin sync
- **Theme/vibe system**, dark mode, and per‑user preferences

Everything is covered by a comprehensive test suite and deploys automatically
using a release script that migrates the database, creates missing columns,
and seeds baseline accounts.

---

## Getting started (development)

1. **Clone and prepare environment**
   ```bash
   git clone https://github.com/ninnis92-stack/process-management-system.git
   cd process-management-prototype
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

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
   default unless `RUN_SEED_ON_RELEASE=0`.

4. **Run the app**
   ```bash
   export FLASK_APP=run.py
   flask run
   ```
   or use Docker Compose (`docker-compose up web`) to start Postgres/Redis
   alongside the web service.

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

---

## Deployment

- `make deploy-safe` builds, tests, and pushes the container to Fly.
- The image’s `entrypoint.sh` ensures databases are available and optionally
  seeds on boot (`SEED_ON_BOOT`, default `1`).
- Fly secrets to set:
  `SECRET_KEY`, `DATABASE_URL`, `SESSION_COOKIE_SECURE=True`,
  `PREFERRED_URL_SCHEME=https`, and any tracker auth tokens.
- Redis is optional; if you set `REDIS_URL` Fly health will check it, otherwise
  it’s skipped.

---

## Feature notes

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

- **Admin console**: located under `/admin` with subpages for users, departments,
  workflows, statuses, site configuration, integrations, feature flags, guest
  form templates, etc.
- **User settings**: dark mode, theme/vibe selection, quote set, rotating
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
behavior, and the admin‑template/requirement engine.

---

Enjoy building and customizing your request workflows! Feedback and patches
are welcome via the GitHub repository.
