# Monitoring & Alerting

This app already exposes runtime health and Prometheus-compatible metrics.
This document shows how to wire them into production monitoring.

## Built-in endpoints

- `/health` – liveness
- `/ready` – readiness with database verification
- `/metrics` – Prometheus exposition

## Prometheus

Use the sample scrape config in [ops/prometheus/fly-scrape.yml](../ops/prometheus/fly-scrape.yml).

Minimum checks to alert on:

- `up == 0`
- readiness probe not returning HTTP 200
- sudden drops in request throughput
- elevated failed webhook deliveries / retry backlog

## Sentry

`sentry-sdk` is installed with the Flask integration. Set these secrets/env vars:

- `SENTRY_DSN`
- `SENTRY_ENVIRONMENT=production`

The app initializes Sentry automatically when a DSN is present.

## PagerDuty

Use `scripts/notify_pagerduty.py` from CI or scheduled monitoring runs.

Recommended secret:

- `PAGERDUTY_ROUTING_KEY`

## Scheduled production checks

The workflow [.github/workflows/production-monitoring.yml](../.github/workflows/production-monitoring.yml)
runs smoke checks against the deployed Fly app on a schedule and can trigger a
PagerDuty incident when checks fail.

Suggested GitHub secrets:

- `PRODUCTION_BASE_URL`
- `PRODUCTION_ADMIN_EMAIL`
- `PRODUCTION_ADMIN_PASSWORD`
- `WEBHOOK_SHARED_SECRET`
- `PAGERDUTY_ROUTING_KEY`

## Production-only smoke coverage

Use these scripts after deploys or in scheduled checks:

- `scripts/smoke_test.sh`
- `scripts/smoke_deployed_login.py`
- `scripts/admin_smoke.py`
- `scripts/webhook_smoke.py`
- `scripts/clear_smoke_remote.py`