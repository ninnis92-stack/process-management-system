# Maintainer Notes & Deployment History

This document accumulates the longer form notes that used to live in the
README.  It is primarily intended for maintainers who want to audit recent
changes, deployments or configuration details; end‑users and new readers
can safely ignore it and follow the shorter summary in `README.md`.

## Live deployment checks & logs

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
- Ran deployed smoke checks with `bash scripts/smoke_test.sh https://process-management-prototype-lingering-bush-6175.fly.dev`, `python scripts/smoke_deployed_login.py --url https://process-management-prototype-lingering-bush-6175.fly.dev`, and `python scripts/admin_smoke.py`; seeded user and admin logins both succeeded and the checked admin/metrics routes returned HTTP 200.
- Cleared remote smoke data with `python scripts/clear_smoke_remote.py`; the cleanup endpoint completed successfully and reported `{"deleted":0}`.
- Checked both `https://process-management-prototype-lingering-bush-6175.fly.dev/ready` and `https://process-management-prototype-lingering-bush-6175.fly.dev/health`; both returned `{"status":"ok"}`, and `/ready` reported `components.database.status: ok`.
- The login page now uses the `motivational` quote set when rolling quotes are enabled; the site-wide default also now resolves to `motivational` unless an admin explicitly chooses another active set. A new `chores` quote set was added so laundry and household routines live in a consistent motivational theme instead of feeling out of place.
- Added client‑side persistence for toggle checkboxes (feature flags and similar forms), ensuring their on/off state survives page refreshes after saving.

## Feature notes

* Guest forms can now specify access policies (`public`, `sso_linked`,
  `approved_sso_domains` or `unaffiliated_only`) and a layout preference
  (`Standard`, `Compact`, or `Spacious`) that is also exposed via the
  `/api/templates/.../external-schema` endpoint for external form builders.
* The app emits a `/ready` readiness probe and logs `quote_sets=ok` during
  release; the release script backfills new columns and normalizes quote data.
* Department-heads may be granted `can_change_priority` per department and
  temporary assignments now define default handoff docs/checklists.
* Dark mode disables the personal vibe picker; adopted brand presets still
  tint the native dark palette and the navbar vibe button is hidden under those
  conditions.
* Rolling quotes are fully random and rotate every 8 seconds; the old
  separate banner has been removed.
* Notification templates are now per-department, and large email sends can run
  in the background via RQ while still recording in-app notifications.
* The review workflow prevents ping-pong loops and renders ``last 5`` steps on
  the request detail page.
* Quote-set permissions may be restricted by department or user email in the
  site config UI; admin users bypass the rules.
* Release-task schema fixes now include guest-form columns, quote-set
  validation, and various new user/department handoff fields.

## Changelog

All notable changes are tracked in git history; the chronological record
above highlights the major deployment milestones.  Refer to commit messages
for more detail.
