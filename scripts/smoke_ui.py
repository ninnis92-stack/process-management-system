#!/usr/bin/env python3
"""Simple programmatic smoke tests for key UI routes using Flask test client.

Usage: PYTHONPATH=. python3 scripts/smoke_ui.py
"""
from app import create_app

app = create_app()

ROUTES = [
    '/',
    '/auth/login',
    '/external',
    '/metrics',
    '/admin/users'
]

if __name__ == '__main__':
    with app.test_client() as c:
        for r in ROUTES:
            resp = c.get(r)
            print(f"GET {r}: {resp.status_code} (len={len(resp.get_data(as_text=True))})")
            # show a brief excerpt for manual inspection when helpful
            body = resp.get_data(as_text=True)
            print(body[:200].replace('\n',' '))
            print('-' * 60)
