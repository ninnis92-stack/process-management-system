#!/usr/bin/env python3
"""Login as seeded admin and POST to /admin/debug/cleanup to clear smoke rows."""
import argparse
import os
import re
import requests
from urllib.parse import urljoin

def get_csrf(session, url):
    r = session.get(url, timeout=10)
    r.raise_for_status()
    m = re.search(r'<meta name="csrf-token" content="([^"]+)">', r.text)
    return m.group(1) if m else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("SMOKE_BASE_URL") or "https://process-management-prototype-lingering-bush-6175.fly.dev")
    parser.add_argument("--email", default=os.getenv("SMOKE_ADMIN_EMAIL") or "admin@example.com")
    parser.add_argument("--password", default=os.getenv("SMOKE_ADMIN_PASSWORD") or "admin123")
    args = parser.parse_args()
    session = requests.Session()
    base = args.url.rstrip("/")

    try:
        csrf = get_csrf(session, urljoin(base, "/auth/login"))
        if not csrf:
            print("No CSRF token found; abort")
            return 2
        r = session.post(
            urljoin(base, "/auth/login"),
            data={"email": args.email, "password": args.password, "csrf_token": csrf},
            allow_redirects=True,
            timeout=10,
        )
        print("login status", r.status_code)
        print("login url:", r.url)
        print("login history:", [h.status_code for h in r.history])
        print("session cookies after login:", session.cookies.get_dict())
        if r.status_code != 200:
            print("Login failed")
            return 3

        # fetch admin page to get csrf token for subsequent POST
        admin_csrf = get_csrf(session, urljoin(base, "/admin"))
        payload = {"csrf_token": admin_csrf} if admin_csrf else {}
        # POST cleanup
        r2 = session.post(
            urljoin(base, "/admin/debug/cleanup?confirm=true"), data=payload, timeout=10
        )
        print("/admin/debug/cleanup ->", r2.status_code)
        print("URL:", r2.url)
        print("History:", [h.status_code for h in r2.history])
        print("Content-Type:", r2.headers.get("Content-Type"))
        print("Body snippet:", r2.text[:1000])
        return 0
    except Exception as exc:
        print("Error during remote cleanup:", exc)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
