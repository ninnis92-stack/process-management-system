#!/usr/bin/env python3
"""Run DB setup and optional seeding during deploy.

This script is intended to be used as a deploy `release_command` so it runs
once per deployment before new instances receive traffic. It will create
tables (via `db.create_all()`) and run `seed.py` when SSO is not enabled in
the app config (so demo accounts are present for non-SSO deployments).
"""
import os
import sys

sys.path.append("/app")

import sys
from pathlib import Path

# Ensure project root is on sys.path so `from app import create_app` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import subprocess

from sqlalchemy import inspect, text

from app import create_app


def _ensure_quote_sets_ready():
    """Normalize and verify quote sets so deploys always have loadable quotes."""
    from app import db
    from app.models import SiteConfig

    cfg = SiteConfig.get()
    normalized_sets = SiteConfig.normalize_quote_sets(
        getattr(cfg, "rolling_quote_sets", None)
    )

    if normalized_sets != (getattr(cfg, "rolling_quote_sets", None) or {}):
        cfg._rolling_quote_sets = json.dumps(normalized_sets)
        print("quote_sets=normalized")

    active = (
        str(getattr(cfg, "active_quote_set", None) or "").strip().lower()
        or "motivational"
    )
    if active not in normalized_sets or active == "default":
        active = "motivational" if "motivational" in normalized_sets else "default"
        cfg.active_quote_set = active
        print("quote_sets=active_reset_to_motivational")

    missing = [name for name, quotes in normalized_sets.items() if not quotes]
    if missing:
        raise RuntimeError(f"quote sets missing content: {', '.join(sorted(missing))}")

    db.session.commit()
    print(
        f"quote_sets=ok total={len(normalized_sets)} active={active} active_count={len(normalized_sets.get(active) or [])}"
    )


def _default_workflow_spec():
    steps = [
        {"from_dept": "A", "to_dept": "B", "status": "NEW_FROM_A"},
        {"from_dept": "B", "to_dept": "B", "status": "B_IN_PROGRESS"},
        {"from_dept": "B", "to_dept": "C", "status": "PENDING_C_REVIEW"},
        {"from_dept": "C", "to_dept": "B", "status": "B_FINAL_REVIEW"},
        {"from_dept": "B", "to_dept": "A", "status": "SENT_TO_A"},
        {"from_dept": "A", "to_dept": "B", "status": "CLOSED"},
    ]
    transitions = []
    for i in range(len(steps) - 1):
        transitions.append(
            {
                "from": steps[i]["status"],
                "to": steps[i + 1]["status"],
                "from_status": steps[i]["status"],
                "to_status": steps[i + 1]["status"],
                "from_dept": steps[i].get("to_dept") or steps[i].get("from_dept"),
                "to_dept": steps[i + 1].get("to_dept") or steps[i + 1].get("from_dept"),
            }
        )
    return {"steps": steps, "transitions": transitions}


def main():
    app = create_app()
    with app.app_context():
        # Report which database we're connected to and run Alembic migrations
        from app import db
        conn = db.engine.connect()
        print("db_engine_url=", conn.engine.url)
        conn.close()

        try:
            rc = subprocess.run(["alembic", "upgrade", "head"], check=False)
            if rc.returncode == 0:
                print("alembic_upgrade=ok")
            else:
                print("alembic_upgrade=head_failed", rc.returncode)
                try:
                    rc2 = subprocess.run(["alembic", "upgrade", "heads"], check=False)
                    if rc2.returncode == 0:
                        print("alembic_upgrade=heads_ok")
                    else:
                        print("alembic_upgrade=heads_failed", rc2.returncode)
                except FileNotFoundError:
                    print("alembic not found on fallback; skipping migrations")
                except Exception as exc2:
                    print("alembic_upgrade_heads_exception", exc2, file=sys.stderr)
        except FileNotFoundError:
            print("alembic not found; skipping migrations")
        except Exception as exc:
            print("alembic_upgrade_exception", exc, file=sys.stderr)

        # ensure certain columns exist even if alembic misfires
        try:
            with db.engine.connect() as c:
                insp = inspect(c)
                # request.original_sender
                cols = [col['name'] for col in insp.get_columns('request')]
                if 'original_sender' not in cols:
                    c.execute(text("ALTER TABLE request ADD COLUMN original_sender VARCHAR(255)"))
                    print("added_column original_sender")
                # site_config.company_url
                cols2 = [col['name'] for col in insp.get_columns('site_config')]
                if 'company_url' not in cols2:
                    c.execute(text("ALTER TABLE site_config ADD COLUMN company_url VARCHAR(255)"))
                    print("added_column company_url")
        except Exception as exc:
            print("column_ensure_exception", exc, file=sys.stderr)

        # Safety net for environments where Alembic is not configured (e.g. no
        # alembic.ini in image) so deployments still converge on required schema.
        # Manual schema workarounds and db.create_all() removed. Only Alembic migrations are run in production.
