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
TENANT_TAG=${IMAGE_NAME}:${TENANT}-${TAG}
docker tag ${IMAGE_NAME}:${TAG} ${TENANT_TAG}

echo "Running migrations and seed in a temporary container..."
docker run --rm \
  -e DATABASE_URL=${DATABASE_URL:-} \
  -e SECRET_KEY=${SECRET_KEY:-notsecret} \
  -e AUTO_CREATE_DB=0 \
  ${IMAGE_NAME}:${TAG} /bin/sh -c "python3 -m migrations.apply_local_sqlite_migrations || true; flask db upgrade || true; python3 seed.py || true"

if [ -n "${REGISTRY:-}" ]; then
  # tag and push to provided registry (e.g. ghcr.io/org/repo)
  FULL_TAG=${REGISTRY}/${IMAGE_NAME}:${TENANT}-${TAG}
  echo "Tagging for registry: ${FULL_TAG}"
  docker tag ${IMAGE_NAME}:${TAG} ${FULL_TAG}
  echo "Pushing ${FULL_TAG}"
  docker push ${FULL_TAG}
  echo "Pushed image to registry: ${FULL_TAG}"
else
  echo "No REGISTRY provided — image is local only: ${TENANT_TAG}"
fi

echo "Tenant ${TENANT} image prepared."

echo "Next steps: push image to your registry (if not already pushed) and deploy using the docker-compose.template.yml or Helm chart in deploy/helm/."
