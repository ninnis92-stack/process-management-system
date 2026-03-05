#!/usr/bin/env python3
"""Wait until the application DB is responsive.

This script imports the Flask app and performs a trivial DB query in a loop
until it succeeds or a timeout is reached. It's intended for use from
`scripts/entrypoint.sh` so container startup can wait until the DB is usable.
"""
import time
import argparse

from app import create_app
from app.extensions import db
from sqlalchemy import text


def wait(timeout: int = 30, interval: float = 1.0) -> int:
    app = create_app()
    deadline = time.time() + timeout
    with app.app_context():
        while True:
            try:
                db.session.execute(text("SELECT 1"))
                print("db_ready")
                return 0
            except Exception as exc:
                if time.time() > deadline:
                    print(f"timeout waiting for db: {exc}")
                    return 2
                time.sleep(interval)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--interval", type=float, default=1.0)
    args = p.parse_args()
    raise SystemExit(wait(timeout=args.timeout, interval=args.interval))


if __name__ == "__main__":
    main()
