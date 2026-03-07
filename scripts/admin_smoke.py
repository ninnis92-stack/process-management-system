#!/usr/bin/env python3
"""Smoke test: log in as seeded admin and check admin pages on deployed app."""
import re
import sys
import requests
from urllib.parse import urljoin

BASE = "https://process-management-prototype-lingering-bush-6175.fly.dev"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PW = "admin123"

session = requests.Session()


def get_csrf(session, url):
    r = session.get(url, timeout=10)
    r.raise_for_status()
    m = re.search(r'<meta name="csrf-token" content="([^"]+)">', r.text)
    return m.group(1) if m else None


def main():
    try:
        csrf = get_csrf(session, urljoin(BASE, "/auth/login"))
        print("GET /auth/login -> csrf", bool(csrf))
        if not csrf:
            print("No CSRF token found; abort")
            return 2
        r = session.post(
            urljoin(BASE, "/auth/login"),
            data={"email": ADMIN_EMAIL, "password": ADMIN_PW, "csrf_token": csrf},
            allow_redirects=True,
            timeout=10,
        )
        print("POST /auth/login ->", r.status_code)

        paths = [
            "/admin/special_email",
            "/admin/feature_flags",
            "/admin/users",
            "/admin/assignments",
            "/metrics",
            "/metrics/json",
        ]
        for p in paths:
            try:
                rr = session.get(urljoin(BASE, p), timeout=10)
                print(
                    f"GET {p} ->",
                    rr.status_code,
                    "len=",
                    len(rr.text) if rr.text else 0,
                )
                if 500 <= rr.status_code <= 599:
                    print("Server error on", p)
            except Exception as e:
                print("Error requesting", p, e)
        # test metrics json if available
        try:
            rj = session.get(urljoin(BASE, "/metrics/json"), timeout=10)
            if rj.status_code == 200:
                print("metrics/json keys:", list(rj.json().keys())[:10])
        except Exception:
            pass
        return 0
    except Exception as exc:
        print("Error during admin smoke:", exc)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
