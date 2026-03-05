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

import sys
from pathlib import Path

# Ensure project root is on sys.path so `from app import create_app` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
import subprocess


def main():
    app = create_app()
    with app.app_context():
        # Run Alembic migrations to bring the DB schema up-to-date. This is
        # the recommended production approach instead of `db.create_all()`.
        try:
            # Prefer invoking the local `alembic` CLI so the virtualenv
            # packaged in the deployment image runs the right code.
            rc = subprocess.run(["alembic", "upgrade", "head"], check=False)
            if rc.returncode == 0:
                print('alembic_upgrade=ok')
            else:
                print('alembic_upgrade=failed', rc.returncode)
        except FileNotFoundError:
            # Alembic binary not available; skip with a warning.
            print('alembic not found; skipping migrations')
        except Exception as exc:
            print('alembic_upgrade_exception', exc, file=sys.stderr)

        # If SSO is enabled for this deployment, skip seeding so real SSO
        # users are authoritative. Otherwise run the local seed to ensure demo
        # accounts are present for UI/login flows.
        sso_enabled = bool(app.config.get('SSO_ENABLED'))
        if sso_enabled:
            print('SSO enabled; skipping seed')
            return

        # Run the idempotent seed script if present
        try:
            import seed
            seed.main()
            print('seeded')
        except Exception as exc:
            print('seed failed', exc, file=sys.stderr)


if __name__ == '__main__':
    main()
