#!/bin/sh
set -e

# Optional seeding on boot when SEED_ON_BOOT=1
# Auto-create DB tables on boot when AUTO_CREATE_DB is not explicitly disabled.
# Default behavior: create tables unless AUTO_CREATE_DB=0 is set in the environment.
if [ "${AUTO_CREATE_DB:-1}" != "0" ]; then
  echo "AUTO_CREATE_DB enabled: ensuring DB tables exist"
  # Retry table creation for a short period to handle transient startup races
  MAX_ATTEMPTS=${DB_CREATE_ATTEMPTS:-30}
  TRY_INTERVAL=${DB_CREATE_INTERVAL:-2}
  attempt=1
  while [ $attempt -le $MAX_ATTEMPTS ]; do
    echo "Attempt $attempt/$MAX_ATTEMPTS: creating DB tables..."
    if python3 scripts/remote_create_tables.py; then
      echo "DB tables ensured"
      break
    fi
    attempt=$((attempt+1))
    echo "create_tables failed; sleeping ${TRY_INTERVAL}s before retry"
    sleep $TRY_INTERVAL
  done
  if [ $attempt -gt $MAX_ATTEMPTS ]; then
    echo "Warning: DB table creation did not succeed after ${MAX_ATTEMPTS} attempts"
  fi
fi

# Optional seeding on boot when SEED_ON_BOOT=1
if [ "${SEED_ON_BOOT:-0}" = "1" ]; then
  echo "SEED_ON_BOOT=1: running seed.py (best-effort)"
  # run but don't fail boot if seeding fails
  python3 seed.py || true
fi

# Exec the container CMD (e.g. gunicorn)
exec "$@"
