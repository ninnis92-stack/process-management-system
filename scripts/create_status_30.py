#!/usr/bin/env python3
"""Create or update a StatusOption with code '30' using raw sqlite.

This script avoids SQLAlchemy model reflection so it works even when the
database schema is missing recently-added columns. It will insert or
update only the columns that actually exist in the `status_option` table.

Run: python scripts/create_status_30.py
"""
import os
import sqlite3
from datetime import datetime

DB_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")


def sqlite_path_from_uri(uri: str) -> str:
    if uri.startswith("sqlite:///"):
        return uri.split("sqlite:///", 1)[1]
    if uri.startswith("sqlite://") and uri != "sqlite:///:memory:":
        return uri.split("sqlite://", 1)[1]
    raise RuntimeError(f"Unsupported or in-memory DB URI: {uri}")


def main():
    try:
        db_path = sqlite_path_from_uri(DB_URI)
    except Exception as e:
        print("Cannot determine sqlite DB file path:", e)
        return

    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Ensure table exists and discover available columns
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='status_option'"
    )
    if not cur.fetchone():
        print("status_option table does not exist in the database.")
        return

    cur.execute("PRAGMA table_info('status_option')")
    cols = [r[1] for r in cur.fetchall()]

    desired = {
        "code": "30",
        "label": "Reminder Test 30",
        "target_department": "B",
        "notify_on_transfer_only": 0,
        "notify_enabled": 1,
        "screenshot_required": 0,
        "email_enabled": 1,
        "created_at": datetime.utcnow().isoformat(sep=" ", timespec="seconds"),
    }

    # Find existing row by code
    cur.execute("SELECT * FROM status_option WHERE code = ?", (desired["code"],))
    existing = cur.fetchone()

    if existing:
        # Build UPDATE using only supported columns (excluding id and code)
        update_cols = [c for c in desired.keys() if c in cols and c != "code"]
        if not update_cols:
            print("No updatable columns available in status_option; nothing to do.")
            return
        set_clause = ", ".join([f"{c} = ?" for c in update_cols])
        params = [desired[c] for c in update_cols] + [desired["code"]]
        sql = f"UPDATE status_option SET {set_clause} WHERE code = ?"
        cur.execute(sql, params)
        conn.commit()
        print(f"Updated existing status_option with code {desired['code']}")
    else:
        insert_cols = [c for c in desired.keys() if c in cols]
        if not insert_cols:
            print("No writable columns available in status_option; cannot insert.")
            return
        placeholders = ",".join(["?" for _ in insert_cols])
        col_list = ",".join(insert_cols)
        params = [desired[c] for c in insert_cols]
        sql = f"INSERT INTO status_option ({col_list}) VALUES ({placeholders})"
        cur.execute(sql, params)
        conn.commit()
        print(f"Inserted status_option with code {desired['code']}")

    conn.close()


if __name__ == "__main__":
    main()
