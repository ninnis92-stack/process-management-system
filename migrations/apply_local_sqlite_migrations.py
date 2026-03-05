#!/usr/bin/env python3
"""Apply small schema fixes to local SQLite DB used for development.

This script will:
- Add `event_ts` column to `audit_log` if missing.
- Make `request_id` nullable on `audit_log` by recreating the table if necessary.

Run from project root with the active virtualenv python if needed.
"""
import sqlite3
import sys
from config import Config
import os


def get_db_path():
    uri = Config.SQLALCHEMY_DATABASE_URI
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "")
    # fallback paths
    if uri.startswith("sqlite://"):
        return uri.replace("sqlite://", "")
    # prefer the instance DB
    return os.path.join(os.path.dirname(__file__), "..", "instance", "app.db")


def main():
    path = get_db_path()
    path = os.path.abspath(path)
    if not os.path.exists(path):
        # try instance/app.db as fallback
        alt = os.path.join(os.path.dirname(__file__), '..', 'instance', 'app.db')
        alt = os.path.abspath(alt)
        if os.path.exists(alt):
            path = alt
            print('Falling back to', alt)
        else:
            print("DB file not found at:", path)
            sys.exit(0)

    print("Using DB:", path)
    con = sqlite3.connect(path)
    cur = con.cursor()

    cols = cur.execute("PRAGMA table_info('audit_log')").fetchall()
    print('audit_log columns:', cols)
    col_names = [c[1] for c in cols]

    if 'event_ts' not in col_names:
        try:
            cur.execute("ALTER TABLE audit_log ADD COLUMN event_ts DATETIME DEFAULT (CURRENT_TIMESTAMP)")
            print('Added event_ts column')
        except Exception as e:
            print('Failed to add event_ts:', e)

    # Re-query columns because schema may have changed
    cols = cur.execute("PRAGMA table_info('audit_log')").fetchall()
    col_names = [c[1] for c in cols]
    req_info = [c for c in cols if c[1] == 'request_id']
    need_rebuild = False
    if req_info:
        notnull = req_info[0][3]
        if notnull == 1:
            need_rebuild = True

    if need_rebuild:
        print('Rebuilding audit_log to make request_id nullable...')
        cur.execute('''
        CREATE TABLE IF NOT EXISTS audit_log_new (
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
            event_ts DATETIME DEFAULT (CURRENT_TIMESTAMP)
        )
        ''')

        # copy matching columns where possible
        existing = [c for c in ['id','request_id','actor_type','actor_user_id','actor_label','action_type','from_status','to_status','note','created_at','event_ts']]
        existing_present = [c for c in existing if c in col_names]
        print('Copying columns:', existing_present)
        cols_csv = ','.join(existing_present)
        cur.execute(f"INSERT INTO audit_log_new ({cols_csv}) SELECT {cols_csv} FROM audit_log")
        cur.execute('DROP TABLE audit_log')
        cur.execute('ALTER TABLE audit_log_new RENAME TO audit_log')
        print('Rebuild complete')

    con.commit()
    con.close()
    print('Local migrations applied')


if __name__ == '__main__':
    main()
