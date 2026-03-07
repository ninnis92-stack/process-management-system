#!/usr/bin/env bash
# Deploy the current branch to the staging Fly app (do not run without review)
# Edit APP_NAME to match your staging app, or export FLY_APP env var.

set -euo pipefail
APP_NAME=${FLY_APP:-process-management-prototype-staging}

echo "Deploying to Fly app: $APP_NAME"
# build and deploy (no release phase changes will be executed here; follow your normal flow)
/opt/homebrew/bin/flyctl deploy --app "$APP_NAME" --config fly.toml --verbose

echo "Deployment finished. You may want to tail logs and run smoke tests."

echo "To tail logs: /opt/homebrew/bin/flyctl logs -a $APP_NAME --follow"
