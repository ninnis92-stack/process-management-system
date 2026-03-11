#!/usr/bin/env bash
# Deploy the current branch to the staging Fly app (do not run without review)
# Edit APP_NAME to match your staging app, or export FLY_APP env var.

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
APP_NAME=${FLY_APP:-process-management-prototype-staging}
FLY_CONFIG=${FLY_CONFIG:-fly.toml}
FLYCTL_BIN=${FLYCTL_BIN:-$(command -v flyctl || true)}

if [ -z "$FLYCTL_BIN" ]; then
	echo "flyctl not found on PATH. Install it or set FLYCTL_BIN." >&2
	exit 1
fi

if [ ! -f "$ROOT_DIR/$FLY_CONFIG" ]; then
	echo "Fly config not found: $ROOT_DIR/$FLY_CONFIG" >&2
	exit 1
fi

echo "Deploying to Fly app: $APP_NAME"
cd "$ROOT_DIR"

if [ "${RUN_TESTS_BEFORE_DEPLOY:-0}" = "1" ]; then
	if [ -x ".venv/bin/python" ]; then
		echo "Running test suite before deploy"
		UPLOAD_FOLDER="$ROOT_DIR/uploads" PYTHONPATH=. .venv/bin/python -m pytest -q
	else
		echo "Skipping tests because .venv/bin/python is not available"
	fi
fi

# build and deploy (no release phase changes will be executed here; follow your normal flow)
"$FLYCTL_BIN" deploy --app "$APP_NAME" --config "$FLY_CONFIG" --verbose

echo "Deployment finished. You may want to tail logs and run smoke tests."

echo "To tail logs: $FLYCTL_BIN logs -a $APP_NAME --follow"
