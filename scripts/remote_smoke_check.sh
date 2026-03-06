#!/usr/bin/env bash
set -euo pipefail

APP_URL=${1:-}
if [ -z "$APP_URL" ]; then
  echo "Usage: $0 https://your-app.example.com"
  exit 2
fi

echo "Checking ${APP_URL}/health"
http_code=$(curl -fsS -o /dev/null -w "%{http_code}" "${APP_URL}/health")
echo "/health -> ${http_code}"
if [ "${http_code}" -ne 200 ]; then
  echo "Health endpoint not OK"
  exit 2
fi

echo "Checking root"
http_code=$(curl -fsS -o /dev/null -w "%{http_code}" "${APP_URL}/")
echo "/ -> ${http_code}"
if [ "${http_code}" -ge 500 ]; then
  echo "Root returned 5xx"
  exit 2
fi

echo "Checking /auth/login"
http_code=$(curl -fsS -o /dev/null -w "%{http_code}" "${APP_URL}/auth/login")
echo "/auth/login -> ${http_code}"
if [ "${http_code}" -ge 500 ]; then
  echo "Login page returned 5xx"
  exit 2
fi

echo "Remote smoke checks OK"
