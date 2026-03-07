"""
Smoke script to exercise guest submit flow when SSO is available.

Usage:
  - Set `SSO_TEST_COOKIE` to a session cookie value that represents an
    authenticated SSO session for a test account (or implement an SSO flow
    for automated sign-in).
  - Optionally set `BASE_URL` (default: deployed app URL).

This is a helper for manual integration testing; automating SSO end-to-end
requires either a test SSO provider that supports scripting or test credentials
and a headless browser (Playwright). Keep this script as a simple starting
point for later integration.

Example:
  SSO_TEST_COOKIE="session=..." python3 scripts/smoke_sso_submit.py
"""

from __future__ import annotations
import os
import re
import requests

BASE_URL = os.environ.get(
    "BASE_URL", "https://process-management-prototype-lingering-bush-6175.fly.dev"
)
SSO_COOKIE = os.environ.get("SSO_TEST_COOKIE")


def main():
    if not SSO_COOKIE:
        print(
            "SSO_TEST_COOKIE not set. Export a session cookie for a test SSO user and retry."
        )
        print("This script is a placeholder for later SSO automation.")
        return

    session = requests.Session()
    # Attach raw cookie header (caller provides the proper cookie string)
    session.headers.update({"Cookie": SSO_COOKIE})

    url = f"{BASE_URL}/external/new"
    print("GET form...", url)
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        print("GET failed", r.status_code)
        return

    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    if not m:
        print("CSRF token not found in form; SSO session may be invalid.")
        return

    token = m.group(1)
    payload = {
        "csrf_token": token,
        "title": "smoke sso submit",
        "request_type": "instructions",
        "pricebook_status": "in_pricebook",
        "priority": "medium",
        "guest_email": os.environ.get("SSO_TEST_EMAIL", "sso-test@example.com"),
        "guest_name": "SSO Smoke",
        "description": "Smoke test via SSO script",
        "due_at": "",
        "submit": "Submit",
    }

    print("POSTing form as SSO user")
    resp = session.post(url, data=payload, allow_redirects=True, timeout=30)
    print("POST status", resp.status_code)
    if resp.status_code == 200:
        print("Response snippet:\n", resp.text[:800])
    else:
        print("Unexpected status", resp.status_code)


if __name__ == "__main__":
    main()
