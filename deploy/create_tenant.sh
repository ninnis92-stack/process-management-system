#!/usr/bin/env bash
set -euo pipefail

# create_tenant.sh
# Usage: ./create_tenant.sh <tenant-name> [image-tag]
# Builds the image, tags it for the tenant, runs migrations and seeds.

TENANT=${1:-demo}
TAG=${2:-latest}
IMAGE_NAME=${IMAGE_NAME:-process-management-prototype}

echo "Building image ${IMAGE_NAME}:${TAG}..."
docker build -t ${IMAGE_NAME}:${TAG} ..

echo "Tagging image for tenant ${TENANT}..."
docker tag ${IMAGE_NAME}:${TAG} ${IMAGE_NAME}:${TENANT}-${TAG}

echo "Starting temporary container to run migrations and seed..."
docker run --rm \
  -e DATABASE_URL=${DATABASE_URL:-} \
  -e SECRET_KEY=${SECRET_KEY:-notsecret} \
  -e AUTO_CREATE_DB=0 \
  ${IMAGE_NAME}:${TAG} /bin/sh -c "python3 -m migrations.apply_local_sqlite_migrations || true; flask db upgrade || true; python3 seed.py || true"

echo "Tenant ${TENANT} image prepared: ${IMAGE_NAME}:${TENANT}-${TAG}"

echo "Next steps: push image to your registry and deploy using the docker-compose.template.yml (adjust env vars)."
