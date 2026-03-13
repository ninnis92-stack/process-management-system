#!/usr/bin/env bash
# Automated Fly.io volume creation and deployment for FreshProcess

set -e

# Set timezone for San Jose
export TZ="America/Los_Angeles"

# Create pg_data volume in San Jose region (sjc) non-interactively
if ! fly volume list | grep -q pg_data; then
	fly volume create pg_data --region sjc --yes
fi

# Deploy app
make deploy
