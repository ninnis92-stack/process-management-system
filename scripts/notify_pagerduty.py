#!/usr/bin/env python3
"""Send a PagerDuty Events API v2 alert for failed monitoring checks."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--routing-key", default=os.getenv("PAGERDUTY_ROUTING_KEY") or ""
    )
    parser.add_argument(
        "--summary", default="Process Management Prototype monitoring failure"
    )
    parser.add_argument("--severity", default="error")
    parser.add_argument("--source", default=socket.gethostname())
    parser.add_argument("--component", default="production-monitoring")
    parser.add_argument("--group", default="fly-production")
    parser.add_argument("--class-name", dest="class_name", default="deploy-smoke")
    parser.add_argument("--details", default="")
    args = parser.parse_args()

    if not args.routing_key:
        print("No PagerDuty routing key supplied; skipping alert")
        return 0

    details = args.details
    try:
        custom_details = json.loads(details) if details else {}
    except Exception:
        custom_details = {"details": details}

    payload = {
        "routing_key": args.routing_key,
        "event_action": "trigger",
        "payload": {
            "summary": args.summary,
            "source": args.source,
            "severity": args.severity,
            "component": args.component,
            "group": args.group,
            "class": args.class_name,
            "custom_details": custom_details,
        },
    }
    response = requests.post(
        "https://events.pagerduty.com/v2/enqueue",
        json=payload,
        timeout=20,
    )
    print("pagerduty status:", response.status_code)
    if response.status_code >= 400:
        print(response.text)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
