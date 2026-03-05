#!/usr/bin/env python3
"""Simple smoke script that submits several guest requests to the deployed app.

It performs a GET to fetch the CSRF token and session cookie, then POSTs the
form payload for a few requests and verifies the redirect/confirmation banner.
"""
import re
import requests
from urllib.parse import urljoin

BASE = "https://process-management-prototype-lingering-bush-6175.fly.dev"

def get_csrf_and_cookies(session, url):
    r = session.get(url)
    r.raise_for_status()
    # Extract CSRF token from meta tag or hidden field
    m = re.search(r'name="csrf_token" value="([0-9a-fA-F-]+)"', r.text)
    if m:
        return m.group(1)
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', r.text)
    if m:
        return m.group(1)
    # Fallback: look for csrf in form hidden inputs
    m = re.search(r'<input[^>]+name="csrf_token"[^>]+value="([^"]+)"', r.text)
    if m:
        return m.group(1)
    raise RuntimeError("CSRF token not found")


def submit_guest(session, csrf, payload):
    headers = {"Referer": f"{BASE}/external/new"}
    data = payload.copy()
    data["csrf_token"] = csrf
    r = session.post(urljoin(BASE, "/external/new"), data=data, headers=headers, allow_redirects=False)
    return r


def main():
    s = requests.Session()
    for i in range(1, 7):
        csrf = get_csrf_and_cookies(s, BASE + "/external/new")
        payload = {
            'guest_email': f'demo{i}@example.com',
            'guest_name': f'Demo {i}',
            'title': f'Smoke request {i}',
            'due_at': '2099-01-01T12:00',
            'request_type': 'part_number',
            'priority': 'medium',
            'pricebook_status': 'unknown',
            'donor_part_number': f'D{i:03}',
            'target_part_number': f'T{i:03}',
            'no_donor_reason': '',
            'description': 'Automated smoke test',
        }
        r = submit_guest(s, csrf, payload)
        print('Submitted', i, '=>', r.status_code, r.headers.get('Location'))
        if r.status_code in (302, 303):
            # follow the redirect to confirm banner present
            follow = s.get(urljoin(BASE, r.headers['Location']))
            if 'Request #' in follow.text or 'tracking_link' in follow.text:
                print('Confirmation banner detected for', i)
            else:
                print('Warning: confirmation not detected for', i)
        else:
            print('Unexpected status:', r.status_code)
            # Dump a short excerpt for debugging
            print(r.text[:800])


if __name__ == '__main__':
    main()
