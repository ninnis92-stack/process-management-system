# Process Management Prototype

A lightweight Flask application for tracking cross-department requests.

## Quick start (development/test)

1. Clone the repository and enter the directory:
   ```bash
   git clone https://github.com/ninnis92-stack/process-management-system.git
   cd process-management-prototype
   ```

2. Create and activate a virtual environment, then install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Configure the application by editing `config.py` or setting environment
   variables.  At minimum supply a `DATABASE_URL`.

4. Bring the database schema up to date.  For development or testing you can
   choose one of the following:
   ```bash
   flask db upgrade                     # regular Alembic migration
   # or — bonus: run the same safety script used in production:
   python scripts/release_tasks.py      # applies migrations + safe ALTERs
   ```
   The second command is useful when you pull newer code that adds columns
   (e.g. the recent `site_config` banner/quote fields) but your database
   hasn’t been migrated yet.  It will silently add any missing columns and
   never fail.

5. Run the server:
   ```bash
   export FLASK_APP=run.py
   flask run
   ```

6. The full test suite is available via:
   ```bash
   make test
   ```

## Site configuration caution

The `/admin/site_config` page reads from a singleton table.  If the table or
individual columns are absent (common when running an older database against
new code) the route will still render and flash a warning rather than raising
an error.  The codebase includes defensive logic in `SiteConfig.get()` and the
admin view, and a migration (`0036_add_site_config_banner_quotes_fields.py`)
and release task to create any missing columns.

## Features

- Workflows with statuses and transitions
- Notifications (in-app or via email)
- Dark mode / per-user themes (“vibes”)
- SSO/OIDC login with optional admin syncing
- Admin UI for users, departments, workflows, feature flags, site config, etc.
- Simple external integration layer and webhooks
- Fly deployment helpers (`make deploy-safe`, `release_tasks.py`)

## Deployment

Deployments use Fly.  `make deploy-safe` runs tests locally, builds a container,
and pushes it to Fly.  The container’s release command runs
`python scripts/release_tasks.py` to automatically fix schema mismatches.

## Changelog

* **2026-03-08** – added site_config banner/quotes columns, defensive admin
  handling, migration and release_task fixes.
* Previous entries available in git history.
