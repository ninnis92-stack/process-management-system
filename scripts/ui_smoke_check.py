"""Quick local smoke-check using Flask test client.

Run from the project root with the virtualenv active:

    python3 scripts/ui_smoke_check.py

This will create the app, make a few GET requests and exit with
non-zero status if any request returns 5xx.
"""
import sys
from app import create_app

CHECKS = [
    "/health",
    "/",
    "/auth/login",
]


def main():
    app = create_app()
    with app.test_client() as client:
        failures = []
        for path in CHECKS:
            try:
                r = client.get(path)
                code = r.status_code
                print(f"GET {path} -> {code}")
                if 500 <= code <= 599:
                    failures.append((path, code))
            except Exception as e:
                print(f"Error requesting {path}: {e}")
                failures.append((path, str(e)))

    if failures:
        print("Smoke check FAILED", failures)
        sys.exit(2)
    print("Smoke check OK")


if __name__ == '__main__':
    main()
