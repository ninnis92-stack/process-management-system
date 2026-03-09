# Admin Features

This document describes the admin-facing features added in recent work.

- Departments: Admins can create, edit, and delete departments at `/admin/departments`.
- SiteConfig: Admins can set an HTML banner and a list of rolling quotes at `/admin/site_config`.
  - `banner_html` is rendered as-is in the navbar when set.
  - `rolling_quotes` is a newline-separated list in the admin editor; when enabled the app will rotate the quotes in the navbar.  The built-in quote sets each contain 30 entries by default, and the "motivational" set has been expanded with a wider, more diverse collection of messages.  Quotes are chosen randomly on each page load and during automatic rotation so there is no fixed cycle.

Running tests

- Tests covering these features: `tests/test_admin_site_config.py`.
- Run all tests:

```bash
PYTHONPATH=. pytest -q
```
