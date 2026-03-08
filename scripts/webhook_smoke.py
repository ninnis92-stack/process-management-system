#!/usr/bin/env python3
"""Production-safe smoke checks for signed webhook endpoints.

By default this verifies that unsigned requests are rejected with HTTP 401.
When `--secret` is provided it also verifies that a correctly signed request
is accepted by `/integrations/incoming-webhook`.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time

import requests


def _sign(secret: str, payload: bytes, timestamp: str | None = None) -> str:
    body = payload if not timestamp else timestamp.encode("utf-8") + b"." + payload
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://process-management-prototype-lingering-bush-6175.fly.dev",
    )
    parser.add_argument("--secret", default="")
    parser.add_argument("--require-signed", action="store_true")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    endpoint = f"{base}/integrations/incoming-webhook"
    payload = {"smoke": True, "source": "github-actions", "ts": int(time.time())}
    raw = json.dumps(payload).encode("utf-8")

    unsigned = requests.post(
        endpoint,
        data=raw,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    print("unsigned webhook:", unsigned.status_code)
    if unsigned.status_code != 401:
        print("Expected unsigned webhook to be rejected with 401")
        return 2

    if not args.secret:
        if args.require_signed:
            print("Signed verification required but no secret was supplied")
            return 3
        print("No webhook secret supplied; unsigned rejection check only")
        return 0

    timestamp = str(int(time.time()))
    sig = _sign(args.secret, raw, timestamp=timestamp)
    signed = requests.post(
        endpoint,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": sig,
        },
        timeout=15,
    )
    print("signed webhook:", signed.status_code)
    if signed.status_code != 204:
        print("Expected signed webhook to be accepted with 204")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())