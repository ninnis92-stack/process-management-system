#!/usr/bin/env python3
"""Smoke test: log in as seeded admin and check admin pages on deployed app."""
import argparse
import os
import re
from urllib.parse import urljoin

import requests


def get_csrf(session, url):
    r = session.get(url, timeout=10)
    r.raise_for_status()
    m = re.search(r'<meta name="csrf-token" content="([^"]+)">', r.text)
    return m.group(1) if m else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default=os.getenv("SMOKE_BASE_URL")
        or "https://process-management-prototype-lingering-bush-6175.fly.dev",
    )
    parser.add_argument(
        "--email", default=os.getenv("SMOKE_ADMIN_EMAIL") or "admin@example.com"
    )
    parser.add_argument(
        "--password", default=os.getenv("SMOKE_ADMIN_PASSWORD") or "admin123"
    )
    args = parser.parse_args()
    session = requests.Session()
    base = args.url.rstrip("/")

    try:
        csrf = get_csrf(session, urljoin(base, "/auth/login"))
        print("GET /auth/login -> csrf", bool(csrf))
        if not csrf:
            print("No CSRF token found; abort")
            return 2
        r = session.post(
            urljoin(base, "/auth/login"),
            data={"email": args.email, "password": args.password, "csrf_token": csrf},
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
                rr = session.get(urljoin(base, p), timeout=10)
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
            rj = session.get(urljoin(base, "/metrics/json"), timeout=10)
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
