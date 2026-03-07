-- Safe idempotent SQL to ensure the `feature_flags.enable_external_forms` column exists.
-- Review and run on a backup/staging DB before applying to production.

ALTER TABLE feature_flags
    ADD COLUMN IF NOT EXISTS enable_external_forms boolean NOT NULL DEFAULT false;

-- If you have other missing columns referenced in logs, add similar ALTER statements here.
-- Example:
-- ALTER TABLE feature_flags
--     ADD COLUMN IF NOT EXISTS some_other_flag boolean NOT NULL DEFAULT false;
