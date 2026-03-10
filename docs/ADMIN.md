# Admin Features

This document describes the admin-facing features added in recent work.

- Departments: Admins can create, edit, and delete departments at `/admin/departments`.
  - When editing a department you may now specify a **notification template** (simple
    Jinja2 text) which will be rendered into the body of any notifications sent to
    users whose primary department matches.  This allows custom prefixes or
    formatting on a per‑department basis.
- SiteConfig: Admins can set an HTML banner and a list of rolling quotes at `/admin/site_config`.
  - `banner_html` is rendered as-is in the navbar when set.
  - `rolling_quotes` is a newline-separated list in the admin editor; when enabled the app will rotate the quotes in the navbar.  The built-in quote sets each contain 30 entries by default, and the "motivational" set has been expanded with a wider, more diverse collection of messages.  Quotes are chosen randomly on each page load and during automatic rotation so there is no fixed cycle.

- Coverage calendar: A download link labelled "Download .ics" appears on the
  coverage calendar view (`/admin/users/coverage`).  The exported iCalendar file
  contains events for each temporary loan respecting the current department/day
  filters, so you can import assignments into external calendar apps.
- User department loans: temporary assignments can now include a lightweight
  handoff package made up of a document URL and a per-line checklist. These are
  shown in the assignment editor, rendered on the coverage calendar, and folded
  into the `.ics` export description so handoff details travel with the event.

Running tests

- Tests covering these features: `tests/test_admin_site_config.py`.
- Run all tests:

```bash
PYTHONPATH=. pytest -q
```
