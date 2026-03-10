#!/usr/bin/env python3
"""Bootstrap a new tenant using the Flask CLI command."""

import os
import subprocess
import sys


def main() -> int:
    env = os.environ.copy()
    env.setdefault("FLASK_APP", "run.py")
    command = ["flask", "onboard-tenant", *sys.argv[1:]]
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
