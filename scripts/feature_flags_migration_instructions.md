# Feature Flags Migration — Instructions

This file contains a safe, idempotent SQL snippet to add the missing `feature_flags.enable_external_forms` column.

1. Run locally against a copy of the database or on a staging instance first.

Example (using `psql`):

```bash
# ensure you have a DB dump or snapshot
psql "$DATABASE_URL" -f migrations/sql/add_feature_flags_columns.sql
```

2. If you prefer to apply via Alembic, create a small revision that executes the same SQL (use `op.execute(...)`).

3. After applying, verify the app no longer logs "UndefinedColumn" errors referencing `feature_flags.enable_external_forms`.

4. If you use automated deploy/release hooks, ensure migrations are applied before the web process runs or stamp the DB appropriately.
