#!/usr/bin/env python3
"""Wait until Redis is responsive when configured.

Used by the container entrypoint so startup can confirm Redis-backed features
are available before the app begins serving traffic.
"""
import argparse
import os
import sys
import time

try:
    import redis
except Exception:
    redis = None


def wait(timeout: int = 30, interval: float = 1.0) -> int:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("redis_not_configured")
        return 0
    if redis is None:
        print("redis_package_missing")
        return 2

    client = redis.from_url(redis_url, decode_responses=True)
    deadline = time.time() + timeout
    while True:
        try:
            client.ping()
            print("redis_ready")
            return 0
        except Exception as exc:
            if time.time() > deadline:
                print(f"timeout waiting for redis: {exc}")
                return 2
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    raise SystemExit(wait(timeout=args.timeout, interval=args.interval))


if __name__ == "__main__":
    main()
