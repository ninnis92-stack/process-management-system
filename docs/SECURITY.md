# Security Checklist

This document captures recommended security hardening steps before promoting to production.

Secrets & credentials
- Store all secrets in your platform's secret store (Fly secrets, GitHub Actions secrets, or environment manager).
- Required secrets: `SECRET_KEY`, `DATABASE_URL`, `WEBHOOK_SHARED_SECRET`, `SMTP_*` (if email enabled), `FLY_API_TOKEN` (for CI deploys), `AWS_*` (for backup uploads).
- Rotate shared secrets periodically and on personnel changes.

Authentication & SSO
- Enable `SSO_ENABLED=true` for production and set `SSO_REQUIRE_MFA=true` to require MFA for admin users when your IdP provides the `amr` claim.
- Enforce admin-only routes behind SSO and audit access.

Web security
- Add a strong Content Security Policy (CSP) and enforce it via response headers.
- Enable HSTS (Strict-Transport-Security) and secure cookie flags for session cookies.
- Limit CORS to trusted origins.

Network & runtime
- Use TLS for all external endpoints (Fly provides TLS for custom domains).
- Limit inbound webhook sources by validating `X-Webhook-Signature` and use a distinct `WEBHOOK_SHARED_SECRET` per integration if possible.

Dependency & secrets scanning
- Enable Dependabot or other dependency scanners for CVE alerts.
- Scan repository for accidental secrets (git-secrets, trufflehog) and purge any accidental disclosures.

Incident response
- Connect Sentry or similar to capture exceptions and rollups.
- Configure alerting on error rate and uptime checks.

Notes
- This checklist is intentionally concise; adapt it to your company's security policies and compliance needs.
