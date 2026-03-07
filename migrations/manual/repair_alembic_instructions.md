# Repair Alembic Revision Graph — Guidance

If your release logs complain about a missing revision (e.g. `KeyError: '0007_autogen_add_special_email_config'`), you can safely reconcile the graph with one of the following approaches (pick one after backing up DB):

Option A — Apply SQL then stamp:
1. Run the idempotent SQL in `migrations/sql/add_feature_flags_columns.sql` on staging/production.
2. Run `alembic stamp head` to mark the DB as up-to-date with the repository revisions (only do this if you're confident the DB matches the migration state).

Option B — Create a consolidation migration:
1. Create a new Alembic revision that contains only `op.execute(...)` statements for any missing schema pieces (use `alembic revision -m "consolidate schema"`).
2. Set the `down_revision` to the current head(s) in `migrations/versions` so it becomes the next revision.
3. Apply with `alembic upgrade head`.

Option C — Restore the missing revision file if it exists in an older branch or remote; re-add it to `migrations/versions` and re-run migrations.

Notes & safety:
- Always backup DB before performing schema changes in production.
- Prefer applying SQL in a maintenance window and verify via `SELECT column_name FROM information_schema.columns` that columns exist.
- If you choose to stamp, only do so after you have applied the corresponding schema changes.

If you'd like, I can generate a sample Alembic revision file that executes the same idempotent ALTER TABLE statements — say if you want me to create that file next, tell me and I'll add it under `migrations/versions` (I will not run it against your DB without your permission).
