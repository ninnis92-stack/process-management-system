-- Safe idempotent SQL to add `rolling_quotes_enabled` column to `feature_flags` if missing.
BEGIN;
ALTER TABLE feature_flags ADD COLUMN IF NOT EXISTS rolling_quotes_enabled boolean NOT NULL DEFAULT true;
COMMIT;
