#!/usr/bin/env python3
"""Smoke test against the deployed app: login and fetch dashboard.

Usage: python3 scripts/smoke_deployed_login.py --url https://your-app
"""
import argparse
import re

import requests


def get_csrf_and_cookies(session, login_url):
    r = session.get(login_url, timeout=10)
    r.raise_for_status()
    # meta tag: <meta name="csrf-token" content="...">
    m = re.search(r'<meta name="csrf-token" content="([^"]+)">', r.text)
    token = m.group(1) if m else None
    return token


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    args = p.parse_args()

    session = requests.Session()
    base = args.url.rstrip("/")
    login_url = base + "/auth/login"

    try:
        token = get_csrf_and_cookies(session, login_url)
        if not token:
            print("No CSRF token found on login page; aborting")
            return 2

        payload = {
            "email": "a@example.com",
            "password": "password123",
            "csrf_token": token,
        }
        r = session.post(login_url, data=payload, allow_redirects=True, timeout=10)
        print("Login POST:", r.status_code)
        # fetch dashboard
        dash = session.get(base + "/dashboard", timeout=10)
        print("Dashboard GET:", dash.status_code)
        if dash.status_code == 200:
            print("Dashboard fetched; length=", len(dash.text))
            return 0
        else:
            print("Dashboard unreachable; content snippet:\n", dash.text[:200])
            return 3
    except Exception as e:
        print("Error during smoke:", e)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
