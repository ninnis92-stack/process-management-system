#!/usr/bin/env bash
set -euo pipefail

# Ensure we don't have conflicting migrations that create the same table
ROOT_DIR=$(dirname "$(dirname "$0")")
MIG_DIR="$ROOT_DIR/migrations/versions"

if [ ! -d "$MIG_DIR" ]; then
  echo "No migrations directory found; skipping migration checks."
  exit 0
fi

duplicates=()
# naive check: look for multiple files that might both create special_email_config
if ls "$MIG_DIR"/*0006* 1> /dev/null 2>&1 && ls "$MIG_DIR"/*0007* 1> /dev/null 2>&1; then
  echo "WARNING: Both 0006_* and 0007_* migration files exist; they may conflict."
  echo "If both apply, Alembic may attempt to create the same table twice."
  exit 2
fi

echo "Migration sanity check passed."
