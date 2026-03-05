#!/usr/bin/env python3
"""Simple monitoring probe that checks app health and metrics and alerts via
Slack webhook when configured.

Usage: set `APP_URL` (default picks from env or localhost), optionally set
`SLACK_WEBHOOK` to post alerts. Intended to be run periodically (cron or
external monitoring job) to detect outages such as DB OperationalError spikes
or failed migrations.
"""
import os
import requests
import sys
from urllib.parse import urljoin

APP = os.getenv('APP_URL', 'http://localhost:5001')
SLACK = os.getenv('SLACK_WEBHOOK')


def check():
    ok = True
    details = []
    try:
        r = requests.get(urljoin(APP, '/health'), timeout=5)
        if r.status_code != 200:
            ok = False
            details.append(f'/health returned {r.status_code}')
    except Exception as exc:
        ok = False
        details.append(f'/health error: {exc}')

    try:
        r = requests.get(urljoin(APP, '/metrics'), timeout=5)
        if r.status_code != 200:
            ok = False
            details.append(f'/metrics returned {r.status_code}')
    except Exception as exc:
        ok = False
        details.append(f'/metrics error: {exc}')

    if not ok and SLACK:
        payload = {
            'text': f':rotating_light: App monitor detected issues at {APP}:\n' + '\n'.join(details)
        }
        try:
            requests.post(SLACK, json=payload, timeout=5)
        except Exception:
            pass

    if ok:
        print('ok')
        return 0
    else:
        print('fail:', '; '.join(details))
        return 2


if __name__ == '__main__':
    sys.exit(check())
