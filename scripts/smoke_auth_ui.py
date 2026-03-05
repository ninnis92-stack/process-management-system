#!/usr/bin/env python3
"""Authenticated smoke tests: login and fetch dashboard/admin pages.
Run with: PYTHONPATH=. python3 scripts/smoke_auth_ui.py
"""
from app import create_app

app = create_app()
# Disable CSRF for test client runs
app.config['WTF_CSRF_ENABLED'] = False

USERS = [
    ('a@example.com', 'password123', '/dashboard'),
    ('admin@example.com', 'admin123', '/admin/users'),
]

if __name__ == '__main__':
    with app.test_client() as c:
        for email, pw, target in USERS:
            print(f"Logging in as {email}")
            resp = c.post('/auth/login', data={'email': email, 'password': pw}, follow_redirects=True)
            print(f"Login response: {resp.status_code}; redirect history: {[r.status_code for r in resp.history]}")
            # attempt to access the target page
            r2 = c.get(target)
            print(f"GET {target}: {r2.status_code}; len={len(r2.get_data(as_text=True))}")
            snippet = r2.get_data(as_text=True)[:200].replace('\n',' ')
            print(snippet)
            print('-'*60)
            # logout if possible
            c.post('/auth/logout', data={}, follow_redirects=True)
