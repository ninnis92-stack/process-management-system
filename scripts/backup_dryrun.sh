#!/usr/bin/env bash
set -euo pipefail

# Create a local DB dump (dry-run) without uploading to S3.
OUTDIR=${OUTDIR:-/tmp}
NOW=$(date -u +%Y%m%dT%H%M%SZ)
FNAME="pm-backup-${NOW}.sql.gz"

echo "Creating local DB dump to $OUTDIR/$FNAME"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is not set; cannot create DB dump." >&2
  exit 2
fi

pg_dump "$DATABASE_URL" | gzip > "$OUTDIR/$FNAME"
echo "Dump created: $OUTDIR/$FNAME"
