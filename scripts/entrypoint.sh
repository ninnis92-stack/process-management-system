#!/bin/sh
set -e

# Optional seeding on boot when SEED_ON_BOOT=1
if [ "${SEED_ON_BOOT:-0}" = "1" ]; then
  echo "SEED_ON_BOOT=1: running seed.py (best-effort)"
  # run but don't fail boot if seeding fails
  python3 seed.py || true
fi

# Exec the container CMD (e.g. gunicorn)
exec "$@"
