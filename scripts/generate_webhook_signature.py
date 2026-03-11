#!/usr/bin/env python3
"""Utility: generate HMAC-SHA256 hex signature for webhook payloads.

Usage:
  python scripts/generate_webhook_signature.py '<secret>' '<payload-file.json>'

Prints the hex digest to stdout.
"""
import hashlib
import hmac
import sys


def main():
    if len(sys.argv) < 3:
        print("Usage: generate_webhook_signature.py <secret> <payload-file>")
        sys.exit(2)
    secret = sys.argv[1].encode("utf-8")
    path = sys.argv[2]
    with open(path, "rb") as f:
        data = f.read()
    mac = hmac.new(secret, data, hashlib.sha256)
    print(mac.hexdigest())


if __name__ == "__main__":
    main()
