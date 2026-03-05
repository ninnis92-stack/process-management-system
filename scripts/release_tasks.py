#!/usr/bin/env python3
"""Run DB setup and optional seeding during deploy.

This script is intended to be used as a deploy `release_command` so it runs
once per deployment before new instances receive traffic. It will create
tables (via `db.create_all()`) and run `seed.py` when SSO is not enabled in
the app config (so demo accounts are present for non-SSO deployments).
"""
import sys
import os

sys.path.append('/app')

from app import create_app
from app.extensions import db


def main():
    app = create_app()
    with app.app_context():
        # Create all tables (idempotent)
        try:
            db.create_all()
            print('created_tables')
        except Exception:
            print('create_all failed; continuing', file=sys.stderr)

        # If SSO is enabled for this deployment, skip seeding so real SSO
        # users are authoritative. Otherwise run the local seed to ensure demo
        # accounts are present for UI/login flows.
        sso_enabled = bool(app.config.get('SSO_ENABLED'))
        if sso_enabled:
            print('SSO enabled; skipping seed')
            return

        # Run the idempotent seed script
        try:
            import seed
            seed.main()
            print('seeded')
        except Exception:
            print('seed failed', file=sys.stderr)


if __name__ == '__main__':
    main()
