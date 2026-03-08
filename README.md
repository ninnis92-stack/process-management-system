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
- Admin-managed verification fields that can auto-fill linked fields on the same request form
- Simple external integration layer and webhooks
- Realtime field verification routing for third-party company trackers via admin-managed verification integration JSON
- Fly deployment helpers (`make deploy-safe`, `release_tasks.py`)

## Realtime tracker-backed field verification

The app now supports a compatibility layer for third-party realtime data-point trackers that verify request field values before or during request submission.

How it works:

- Create or edit an integration at [app/templates/admin_integrations.html](app/templates/admin_integrations.html) using kind `verification`.
- Define one or more tracker handles under `trackers`.
- Add `routing.rules` to choose a tracker by field key or field contents.
- Point a form field verification mapping at provider `verification`.
- Optional field params such as `tracker_handle` can force a specific tracker for one field.

Example verification integration JSON:

```json
{
   "provider": "generic_verification",
   "routing": {
      "default_tracker": "erp",
      "rules": [
         {
            "name": "Serial lookup",
            "tracker": "serial_hub",
            "external_keys": ["serial_number"],
            "starts_with": ["SN-"]
         },
         {
            "name": "Email lookup",
            "tracker": "people_directory",
            "external_keys": ["employee_email"],
            "contains": ["@"]
         }
      ]
   },
   "trackers": {
      "erp": {
         "endpoints": {
            "base_url": "https://erp.example.com",
            "validate": "/api/verify"
         },
         "auth": {
            "type": "token",
            "token_env": "ERP_VERIFY_TOKEN"
         },
         "request": {
            "method": "GET",
            "payload_location": "query",
            "query_template": {
               "value": "{value}",
               "field": "{external_key}"
            }
         },
         "response": {
            "ok_path": "ok",
            "detail_path": "details",
            "reason_path": "reason"
         }
      }
   }
}
```

Supported routing matchers in `routing.rules`:

- `external_keys`
- `equals` / `equals_any`
- `contains` / `contains_any`
- `starts_with` / `starts_with_any`
- `ends_with` / `ends_with_any`
- `regex`
- `min_length` / `max_length`
- `option_matches` for rule selection from extra params

## Configuration validation and auditing

Before launching in production you can run `flask check-config` to perform
basic sanity checks on environment variables.  This command uses
`Config.validate()` and emits human-readable errors when secrets are missing
or required settings (e.g. SMTP_HOST when EMAIL_ENABLED) are unset.  The
application also audits any changes made via the admin UI: updates to
`/admin/site_config` create an `AuditLog` row with `action_type` set to
`site_config_update`, ensuring that later reviewers can see who changed the
banner, theme, or quote sets.

## Admin-built request forms

Dynamic request templates can now behave more like guided product forms instead
of flat intake screens:

- Each template may enable `verification_prefill_enabled`, allowing verified
   lookup fields to populate other fields on the same form.
- Each field verification rule may define `prefill_targets` so tracker/integration
   responses can map values such as `details.name` or `details.department` into
   linked request fields.
- The request UI shows when a field is verification-backed and when it can
   auto-fill related fields.

Example field verification params:

```json
{
   "tracker_handle": "directory",
   "prefill_enabled": true,
   "prefill_targets": {
      "employee_name": "details.name",
      "employee_email": {
         "path": "details.email",
         "overwrite": true
      }
   }
}
```

The server also applies these prefills during submission, so required linked
fields can still be populated even if the browser-side enhancement does not run.

## Workflow safety

The request workspace now includes a recent workflow path and recommended next
actions. The transition endpoint also blocks repeated ping-pong moves between
the same two statuses inside a short window, which helps reduce unnecessary
process loops and accidental back-and-forth churn.


## Deployment

Deployments use Fly.  `make deploy-safe` runs tests locally, builds a container,
and pushes it to Fly.  The container’s release command runs
`python scripts/release_tasks.py` to automatically fix schema mismatches.

Fly polish already included in this repo:

- `fly.toml` points readiness checks at `/health`
- `Dockerfile` runs the app on port `8080`
- `scripts/entrypoint.sh` waits for the database before serving traffic
- release tasks run automatically during deploy

### Smoke tests & health endpoints

A simple shell script (`scripts/smoke_test.sh`) exercises the home page,
admin site_config page, and dashboard.  Run it against an active URL as part
of your staging promotion process, e.g.:

```bash
./scripts/smoke_test.sh https://staging.example.com
```

For local verification you can start the server in a background shell and curl
`/health` and `/ready` directly; both endpoints return `200` and include a
`X-Request-ID` header for tracing.  These are wired to Fly’s liveness/readiness
checks already.

Suggested Fly secrets / env for production:

- `SECRET_KEY`
- `DATABASE_URL`
- `SESSION_COOKIE_SECURE=True`
- `PREFERRED_URL_SCHEME=https`
- any tracker auth env vars referenced by verification integrations, such as `ERP_VERIFY_TOKEN`

## Changelog

* **2026-03-08** – added site_config banner/quotes columns, defensive admin
  handling, migration and release_task fixes.
* Previous entries available in git history.
