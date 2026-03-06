# Incident Playbook

This playbook describes first-response steps for a production incident.

1. Triage
   - Check `/health` for 200
   - Check recent deploys and tags
   - Run `flyctl logs -a <app>` for recent errors

2. Contain
   - Scale down worker processes if background jobs causing errors
   - Put app behind maintenance page (if supported)

3. Diagnose
   - Check Sentry / error aggregator for stack traces
   - Check DB: connectivity, slow queries, and storage

4. Mitigate / Rollback
   - If issue introduced in last deploy, roll back to previous tag:

```bash
# Deploy last working tag
git fetch --tags
git checkout tags/<previous-tag> -b rollback-temp
git push origin rollback-temp:main
flyctl deploy -a <app>
```

5. Restore DB (if required)

```bash
pg_restore -d "$DATABASE_URL" /path/to/pre-migration.dump
```

6. Post-incident
   - Run full smoke checks and make sure `/health` is 200
   - Draft incident summary and root cause, communicate to stakeholders

Contact list:

- Primary: ops@example.com
- Secondary: team Slack #ops
