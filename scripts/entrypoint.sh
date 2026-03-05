#!/bin/sh
set -e

# Optional seeding on boot when SEED_ON_BOOT=1
# Auto-create DB tables on boot when AUTO_CREATE_DB is not explicitly disabled.
# Default behavior: create tables unless AUTO_CREATE_DB=0 is set in the environment.
if [ "${AUTO_CREATE_DB:-1}" != "0" ]; then
  echo "AUTO_CREATE_DB enabled: ensuring DB tables exist (best-effort)"
  python3 scripts/remote_create_tables.py || true
fi

# Optional seeding on boot when SEED_ON_BOOT=1
if [ "${SEED_ON_BOOT:-0}" = "1" ]; then
  echo "SEED_ON_BOOT=1: running seed.py (best-effort)"
  # run but don't fail boot if seeding fails
  python3 seed.py || true
fi

# Exec the container CMD (e.g. gunicorn)
exec "$@"
