#!/usr/bin/env python3
"""Migration: make audit_log.request_id nullable for SQLite.

This script backups the existing SQLite DB file and performs a safe table
recreate-and-copy migration so `request_id` can be NULL for system-level audit
entries (e.g., impersonation events).

Usage: python3 scripts/migrate_audit_nullable.py
"""
import os
import shutil
import sqlite3
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.getenv("DATABASE_FILE") or os.path.join(ROOT, "app.db")

if not os.path.exists(DB_PATH):
    print(f"Database file not found: {DB_PATH}")
    raise SystemExit(1)

bak = DB_PATH + f".bak-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
print(f"Backing up DB {DB_PATH} -> {bak}")
shutil.copy2(DB_PATH, bak)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

try:
    # Check current schema for audit_log.request_id notnull
    cur.execute("PRAGMA table_info('audit_log')")
    cols = cur.fetchall()
    if not cols:
        print("No audit_log table present; nothing to do.")
        raise SystemExit(0)
    col_info = {c[1]: c for c in cols}
    if "request_id" in col_info and col_info["request_id"][3] == 0:
        print("audit_log.request_id is already nullable; nothing to do.")
        raise SystemExit(0)

    print("Performing migration: recreate audit_log with nullable request_id...")

    cur.executescript(
        """
    BEGIN;
    CREATE TABLE audit_log_new (
        id INTEGER PRIMARY KEY,
        request_id INTEGER,
        actor_type VARCHAR(20) NOT NULL,
        actor_user_id INTEGER,
        actor_label VARCHAR(255),
        action_type VARCHAR(50) NOT NULL,
        from_status VARCHAR(40),
        to_status VARCHAR(40),
        note TEXT,
        created_at DATETIME,
        event_ts DATETIME NOT NULL
    );

    INSERT INTO audit_log_new (id, request_id, actor_type, actor_user_id, actor_label, action_type, from_status, to_status, note, created_at, event_ts)
    SELECT id, request_id, actor_type, actor_user_id, actor_label, action_type, from_status, to_status, note, created_at, event_ts FROM audit_log;

    DROP TABLE audit_log;
    ALTER TABLE audit_log_new RENAME TO audit_log;
    COMMIT;
    """
    )
    print("Migration completed successfully.")
except Exception:
    con.rollback()
    raise
finally:
    con.close()
