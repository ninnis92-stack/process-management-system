#!/usr/bin/env python3
"""Login as seeded admin and POST to /admin/debug/cleanup to clear smoke rows."""
import re
import sys
import requests
from urllib.parse import urljoin

BASE = 'https://process-management-prototype-lingering-bush-6175.fly.dev'
ADMIN_EMAIL = 'admin@example.com'
ADMIN_PW = 'admin123'

session = requests.Session()


def get_csrf(session, url):
    r = session.get(url, timeout=10)
    r.raise_for_status()
    m = re.search(r'<meta name="csrf-token" content="([^"]+)">', r.text)
    return m.group(1) if m else None


def main():
    try:
        csrf = get_csrf(session, urljoin(BASE, '/auth/login'))
        if not csrf:
            print('No CSRF token found; abort')
            return 2
        r = session.post(urljoin(BASE, '/auth/login'), data={'email': ADMIN_EMAIL, 'password': ADMIN_PW, 'csrf_token': csrf}, allow_redirects=True, timeout=10)
        print('login status', r.status_code)
        if r.status_code != 200:
            print('Login failed')
            return 3

        # POST cleanup
        r2 = session.post(urljoin(BASE, '/admin/debug/cleanup?confirm=true'), timeout=10)
        print('/admin/debug/cleanup ->', r2.status_code, r2.text[:400])
        return 0
    except Exception as exc:
        print('Error during remote cleanup:', exc)
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
