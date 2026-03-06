#!/usr/bin/env bash
# Check required env vars for staging deploy without setting them.
set -euo pipefail

MISSING=()
check() {
  if [ -z "${!1:-}" ]; then
    MISSING+=("$1")
  fi
}

# Common names used in docs and CI
check FLY_API_TOKEN
check FLY_APP
check PLATFORM_API_TOKEN
check STAGING_DATABASE_URL
check STAGING_BASE_URL

if [ ${#MISSING[@]} -ne 0 ]; then
  echo "Missing required environment variables:" >&2
  for v in "${MISSING[@]}"; do
    echo " - $v" >&2
  done
  echo "\nDo NOT store secrets in repo; set them in GitHub Actions secrets or your CI provider." >&2
  exit 2
fi

echo "All required staging env vars appear set (local check)." >&2
echo "You can now run: git push origin HEAD && flyctl deploy -a $FLY_APP" >&2
