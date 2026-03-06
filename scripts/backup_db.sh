#!/usr/bin/env bash
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL must be set"
  exit 2
fi

OUT_DIR=${1:-/backups}
mkdir -p "$OUT_DIR"
OUT_FILE="$OUT_DIR/db-$(date -I).dump"

echo "Backing up DB to $OUT_FILE"
pg_dump -Fc "$DATABASE_URL" -f "$OUT_FILE"
echo "Backup complete"
