#!/usr/bin/env bash
set -euo pipefail

# Simple DB backup script that supports Postgres via `pg_dump` and uploads
# to S3 when `AWS_S3_BUCKET` is configured. Requires `DATABASE_URL` env var.

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL must be set"
  exit 1
fi

OUT_DIR=${1:-/tmp}
TS=$(date -u +"%Y%m%dT%H%M%SZ")
FNAME="pm-proto-db-${TS}.sql.gz"
OUT_PATH="$OUT_DIR/$FNAME"

echo "Dumping DB to $OUT_PATH"

if echo "$DATABASE_URL" | grep -q "^postgres"; then
  pg_dump "$DATABASE_URL" | gzip > "$OUT_PATH"
else
  echo "Unsupported DB type for automated dump; please perform manual backup."
  exit 1
fi

if [ -n "${AWS_S3_BUCKET:-}" ]; then
  if command -v aws >/dev/null 2>&1; then
    echo "Uploading to s3://$AWS_S3_BUCKET/$FNAME"
    aws s3 cp "$OUT_PATH" "s3://$AWS_S3_BUCKET/$FNAME"
  else
    echo "AWS CLI not found; skipping upload"
  fi
fi

echo "Backup complete: $OUT_PATH"
