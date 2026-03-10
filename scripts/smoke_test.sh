#!/usr/bin/env bash
# Simple smoke tests for a deployed staging app. Set STAGING_URL or pass as first arg.

set -euo pipefail
URL=${1:-${STAGING_URL:-https://your-staging-app.example.com}}

echo "Running basic smoke tests against $URL"

# check home
curl -fsS "$URL"/ || (echo 'Home failed' && exit 2)
# check liveness and readiness
curl -fsS "$URL"/health || (echo '/health failed' && exit 3)
curl -fsS "$URL"/ready || (echo '/ready failed' && exit 4)
# check admin (may require login) - check site_config page loads (200)
curl -fsS "$URL"/admin/site_config || echo 'admin/site_config returned non-200'
# check requests index
curl -fsS "$URL"/dashboard || echo 'dashboard returned non-200'

echo "Smoke tests completed (basic HTTP checks). Review logs for errors."
