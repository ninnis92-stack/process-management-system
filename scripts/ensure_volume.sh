#!/usr/bin/env bash
# ensure_volume.sh - create the pg_data volume if it doesn't already exist
set -euo pipefail

app=${FLY_APP:-process-management-prototype}

if ! flyctl volumes list -a "$app" | grep -q "pg_data"; then
    echo "pg_data volume not found for app $app, creating..."
    # size 1GB is a reasonable default; adjust as needed
    flyctl volumes create pg_data -a "$app" --size 1
    echo "pg_data volume created."
else
    echo "pg_data volume already exists for app $app."
fi
