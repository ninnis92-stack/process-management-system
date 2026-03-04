# FlowForge Process Management Prototype

Brief architecture map for reviewers.

## Overview
- Flask app with blueprints: `auth` (login/SSO), `requests_bp` (core workflow), `external` (guest links), `noti***REMOVED***cations` (in-app notices).
- Data layer: SQLAlchemy models in `app/models.py`; migrations are not wired (tables auto-create in dev via `AUTO_CREATE_DB`).
- Frontend: Jinja templates under `app/templates`, static assets under `app/static`.
- Auth: Local login with optional OIDC SSO (see env vars below). Login required for all internal routes.
- Roles: Departments A/B/C drive status transitions and UI hints. Guests can view via tokenized links.

## Quickstart
- Create and activate a virtualenv, then install deps: `pip install -r requirements.txt`.
- Set `FLASK_ENV=development` and `AUTO_CREATE_DB=1` (or set `DATABASE_URL` to point to Postgres/MySQL).
- Seed local data (users, requests, artifacts) with `python3 seed.py`.
- Run the app with `python3 run.py`; default server binds to 0.0.0.0:8080 (see `run.py`).
- Uploads land in `uploads/`; adjust `UPLOAD_FOLDER` env var if needed.

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

## Noti***REMOVED***cations
- Stored in DB via `Noti***REMOVED***cation` model; created via `notify_users` helper in `requests_bp/routes.py`.
- Types include status changes, nudges, and request creation; surfaced in UI banner (template logic in `base.html`).

## Search & Filtering
- Search endpoint `/search` (title/description/id) scoped by department access.
- Dept B dashboard shows status buckets and semantic ***REMOVED***lters (in progress, C review, ***REMOVED***nal review, etc.). Closed items >24h are hidden.

## Nudges
- Only the original submitter can nudge; gated to 48h after creation and 24h cooldown; Dept C cannot send nudges.

## Forms & Validations
- WTForms in `app/requests_bp/forms.py` drive request create/edit/transition forms.
- File uploads stored under `UPLOAD_FOLDER`; only PNG/JPEG/WebP allowed; 10MB per ***REMOVED***le; `MAX_FILES_PER_SUBMISSION` controls count.

## Guest Access
- Guest tokens created per request (`Request.ensure_guest_token`). Guests can view/update via `external` blueprint using tokenized links.

## Environment
- Copy `.env.example` (if present) or set env vars: `FLASK_ENV`, `DATABASE_URL` (or default SQLite), `SECRET_KEY`, `UPLOAD_FOLDER`, `AUTO_CREATE_DB`.
- Optional: `SSO_ENABLED`, `OIDC_*` vars for SSO.

## Dev Notes
- Run `python3 seed.py` to seed sample data.
- Server entrypoint: `run.py` (Flask), Docker***REMOVED***le provided; Fly/Vercel con***REMOVED***gs included for deployment experiments.

## Known Gaps
- No Alembic migrations; schema auto-creates in dev.
- Guest detail page surfaces public submissions/comments only; internal notes stay hidden.
- Placeholder veri***REMOVED***cation endpoint (routes) still needs real lookup logic.
