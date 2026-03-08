#!/usr/bin/env python3
"""Run DB setup and optional seeding during deploy.

This script is intended to be used as a deploy `release_command` so it runs
once per deployment before new instances receive traffic. It will create
tables (via `db.create_all()`) and run `seed.py` when SSO is not enabled in
the app config (so demo accounts are present for non-SSO deployments).
"""
import sys
import os

sys.path.append("/app")

import sys
from pathlib import Path

# Ensure project root is on sys.path so `from app import create_app` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
import subprocess
from sqlalchemy import inspect, text
import json


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
        # Run Alembic migrations to bring the DB schema up-to-date. This is
        # the recommended production approach instead of `db.create_all()`.
        try:
            # Prefer invoking the local `alembic` CLI so the virtualenv
            # packaged in the deployment image runs the right code.
            rc = subprocess.run(["alembic", "upgrade", "head"], check=False)
            if rc.returncode == 0:
                print("alembic_upgrade=ok")
            else:
                # Some repos have multiple heads (merge commits). If the
                # single 'head' target fails, attempt to upgrade all heads
                # which is a safe idempotent fallback.
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
            # Alembic binary not available; skip with a warning.
            print("alembic not found; skipping migrations")
        except Exception as exc:
            print("alembic_upgrade_exception", exc, file=sys.stderr)

        # Safety net for environments where Alembic is not configured (e.g. no
        # alembic.ini in image) so deployments still converge on required schema.
        try:
            db = app.extensions.get("sqlalchemy")
            if db is not None:
                db.create_all()
                engine = db.engine
                insp = inspect(engine)

                # Ensure legacy deployments have expected request columns.
                req_cols = {c["name"] for c in insp.get_columns("request")}
                if "sales_list_reference" not in req_cols:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE request ADD COLUMN sales_list_reference VARCHAR(200)"
                            )
                        )
                    print("schema_fix=request.sales_list_reference_added")

                submission_cols = (
                    {c["name"] for c in insp.get_columns("submission")}
                    if "submission" in insp.get_table_names()
                    else set()
                )
                if (
                    "submission" in insp.get_table_names()
                    and "template_id" not in submission_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE submission ADD COLUMN template_id INTEGER"
                            )
                        )
                    print("schema_fix=submission.template_id_added")
                if (
                    "submission" in insp.get_table_names()
                    and "data" not in submission_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text("ALTER TABLE submission ADD COLUMN data JSONB")
                        )
                    print("schema_fix=submission.data_added")

                notification_cols = (
                    {c["name"] for c in insp.get_columns("notification")}
                    if "notification" in insp.get_table_names()
                    else set()
                )
                if (
                    "notification" in insp.get_table_names()
                    and "read_at" not in notification_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE notification ADD COLUMN read_at TIMESTAMP"
                            )
                        )
                    print("schema_fix=notification.read_at_added")

                special_cols = (
                    {c["name"] for c in insp.get_columns("special_email_config")}
                    if "special_email_config" in insp.get_table_names()
                    else set()
                )
                if (
                    "special_email_config" in insp.get_table_names()
                    and "nudge_min_delay_hours" not in special_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE special_email_config ADD COLUMN nudge_min_delay_hours INTEGER DEFAULT 4"
                            )
                        )
                    print("schema_fix=special_email_config.nudge_min_delay_hours_added")
                # ensure interval/delay columns are stored as floats on
                # databases that support strong typing; this is a no-op on
                # SQLite as it treats types loosely.
                if (
                    "special_email_config" in insp.get_table_names()
                    and "nudge_interval_hours" in special_cols
                    and engine.dialect.name != "sqlite"
                ):
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE special_email_config ALTER COLUMN nudge_interval_hours TYPE FLOAT"
                                )
                            )
                        print("schema_fix=special_email_config.nudge_interval_hours_float")
                    except Exception:
                        pass
                if (
                    "special_email_config" in insp.get_table_names()
                    and "nudge_min_delay_hours" in special_cols
                    and engine.dialect.name != "sqlite"
                ):
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE special_email_config ALTER COLUMN nudge_min_delay_hours TYPE FLOAT"
                                )
                            )
                        print("schema_fix=special_email_config.nudge_min_delay_hours_float")
                    except Exception:
                        pass
                if (
                    "special_email_config" in insp.get_table_names()
                    and "request_form_department" not in special_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE special_email_config ADD COLUMN request_form_department VARCHAR(2) DEFAULT 'A'"
                            )
                        )
                    print(
                        "schema_fix=special_email_config.request_form_department_added"
                    )
                if (
                    "special_email_config" in insp.get_table_names()
                    and "request_form_field_validation_enabled" not in special_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE special_email_config ADD COLUMN request_form_field_validation_enabled BOOLEAN DEFAULT FALSE"
                            )
                        )
                    print(
                        "schema_fix=special_email_config.request_form_field_validation_enabled_added"
                    )
                if (
                    "special_email_config" in insp.get_table_names()
                    and "request_form_inventory_out_of_stock_notify_enabled"
                    not in special_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE special_email_config ADD COLUMN request_form_inventory_out_of_stock_notify_enabled BOOLEAN DEFAULT FALSE"
                            )
                        )
                    print(
                        "schema_fix=special_email_config.request_form_inventory_out_of_stock_notify_enabled_added"
                    )
                if (
                    "special_email_config" in insp.get_table_names()
                    and "request_form_inventory_out_of_stock_notify_mode"
                    not in special_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE special_email_config ADD COLUMN request_form_inventory_out_of_stock_notify_mode VARCHAR(20) DEFAULT 'email'"
                            )
                        )
                    print(
                        "schema_fix=special_email_config.request_form_inventory_out_of_stock_notify_mode_added"
                    )
                if (
                    "special_email_config" in insp.get_table_names()
                    and "request_form_inventory_out_of_stock_message"
                    not in special_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE special_email_config ADD COLUMN request_form_inventory_out_of_stock_message TEXT"
                            )
                        )
                    print(
                        "schema_fix=special_email_config.request_form_inventory_out_of_stock_message_added"
                    )

                status_cols = (
                    {c["name"] for c in insp.get_columns("status_option")}
                    if "status_option" in insp.get_table_names()
                    else set()
                )
                if (
                    "status_option" in insp.get_table_names()
                    and "email_enabled" not in status_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE status_option ADD COLUMN email_enabled BOOLEAN DEFAULT FALSE"
                            )
                        )
                    print("schema_fix=status_option.email_enabled_added")
                if (
                    "status_option" in insp.get_table_names()
                    and "screenshot_required" not in status_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE status_option ADD COLUMN screenshot_required BOOLEAN DEFAULT FALSE"
                            )
                        )
                    print("schema_fix=status_option.screenshot_required_added")
                # Ensure notify_to_originator_only exists on status options
                if (
                    "status_option" in insp.get_table_names()
                    and "notify_to_originator_only" not in status_cols
                ):
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE status_option ADD COLUMN notify_to_originator_only BOOLEAN DEFAULT FALSE"
                                )
                            )
                        print("schema_fix=status_option.notify_to_originator_only_added")
                    except Exception:
                        # Don't fail the whole release on this ALTER; log and continue.
                        print("schema_fix=status_option.notify_to_originator_only_failed")

                department_cols = (
                    {c["name"] for c in insp.get_columns("department")}
                    if "department" in insp.get_table_names()
                    else set()
                )
                if (
                    "department" in insp.get_table_names()
                    and "order" not in department_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                'ALTER TABLE department ADD COLUMN "order" INTEGER DEFAULT 0'
                            )
                        )
                    print("schema_fix=department.order_added")

                site_cols = (
                    {c["name"] for c in insp.get_columns("site_config")}
                    if "site_config" in insp.get_table_names()
                    else set()
                )
                if (
                    "site_config" in insp.get_table_names()
                    and "brand_name" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN brand_name VARCHAR(120)"
                            )
                        )
                    print("schema_fix=site_config.brand_name_added")
                if (
                    "site_config" in insp.get_table_names()
                    and "logo_filename" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN logo_filename VARCHAR(255)"
                            )
                        )
                    print("schema_fix=site_config.logo_filename_added")
                if (
                    "site_config" in insp.get_table_names()
                    and "theme_preset" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN theme_preset VARCHAR(40) DEFAULT 'default'"
                            )
                        )
                    print("schema_fix=site_config.theme_preset_added")
                # newer fields added after 0020 migration; make sure they exist too
                if (
                    "site_config" in insp.get_table_names()
                    and "navbar_banner" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN navbar_banner VARCHAR(500)"
                            )
                        )
                    print("schema_fix=site_config.navbar_banner_added")
                if (
                    "site_config" in insp.get_table_names()
                    and "show_banner" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN show_banner BOOLEAN DEFAULT FALSE"
                            )
                        )
                    print("schema_fix=site_config.show_banner_added")
                if (
                    "site_config" in insp.get_table_names()
                    and "rolling_quotes" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN rolling_quotes TEXT"
                            )
                        )
                    print("schema_fix=site_config.rolling_quotes_added")
                if (
                    "site_config" in insp.get_table_names()
                    and "rolling_quote_sets" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN rolling_quote_sets TEXT"
                            )
                        )
                    print("schema_fix=site_config.rolling_quote_sets_added")
                if (
                    "site_config" in insp.get_table_names()
                    and "active_quote_set" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN active_quote_set VARCHAR(80) DEFAULT 'default'"
                            )
                        )
                    print("schema_fix=site_config.active_quote_set_added")
                if (
                    "site_config" in insp.get_table_names()
                    and "updated_at" not in site_cols
                ):
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE site_config ADD COLUMN updated_at TIMESTAMP"
                            )
                        )
                    print("schema_fix=site_config.updated_at_added")
                # Ensure feature_flags has expected columns added in recent releases.
                if "feature_flags" in insp.get_table_names():
                    ff_cols = {c["name"] for c in insp.get_columns("feature_flags")}
                    if "vibe_enabled" not in ff_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE feature_flags ADD COLUMN vibe_enabled BOOLEAN DEFAULT TRUE"
                                )
                            )
                        print("schema_fix=feature_flags.vibe_enabled_added")
                    if "sso_admin_sync_enabled" not in ff_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE feature_flags ADD COLUMN sso_admin_sync_enabled BOOLEAN DEFAULT TRUE"
                                )
                            )
                        print("schema_fix=feature_flags.sso_admin_sync_enabled_added")
                # Ensure user.last_active_dept exists when model expects it
                if "user" in insp.get_table_names():
                    user_cols = {c["name"] for c in insp.get_columns("user")}
                    if "last_active_dept" not in user_cols:
                        with engine.begin() as conn:
                            # quote user as it's a reserved word in some DBs
                            conn.execute(
                                text(
                                    'ALTER TABLE "user" ADD COLUMN last_active_dept VARCHAR(2)'
                                )
                            )
                        print("schema_fix=user.last_active_dept_added")
                # Ensure new deployments have `dark_mode` column expected by
                # recent releases; create it if missing to avoid seed failures.
                try:
                    if "user" in insp.get_table_names():
                        user_cols = {c["name"] for c in insp.get_columns("user")}
                        if "dark_mode" not in user_cols:
                            with engine.begin() as conn:
                                conn.execute(text('ALTER TABLE "user" ADD COLUMN dark_mode BOOLEAN DEFAULT FALSE'))
                            print("schema_fix=user.dark_mode_added")
                except Exception:
                    # Don't fail the whole release if this ALTER can't be run;
                    # downstream steps will surface the error and be logged.
                    pass
                # Ensure request.is_denied exists when the model expects it
                if "request" in insp.get_table_names():
                    req_cols = {c["name"] for c in insp.get_columns("request")}
                    if "is_denied" not in req_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE request ADD COLUMN is_denied BOOLEAN DEFAULT FALSE"
                                )
                            )
                        print("schema_fix=request.is_denied_added")
                    # Ensure workflow_id exists when the model expects it
                    if "workflow_id" not in req_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE request ADD COLUMN workflow_id INTEGER"
                                )
                            )
                        print("schema_fix=request.workflow_id_added")
                # Ensure status_bucket.workflow_id exists when the model expects it
                if "status_bucket" in insp.get_table_names():
                    sb_cols = {c["name"] for c in insp.get_columns("status_bucket")}
                    if "workflow_id" not in sb_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE status_bucket ADD COLUMN workflow_id INTEGER"
                                )
                            )
                        print("schema_fix=status_bucket.workflow_id_added")
                # Ensure workflow columns expected by the model exist before any ORM query
                if "workflow" in insp.get_table_names():
                    workflow_cols = {c["name"] for c in insp.get_columns("workflow")}
                    if "implementation_pending" not in workflow_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE workflow ADD COLUMN implementation_pending BOOLEAN DEFAULT FALSE"
                                )
                            )
                        print("schema_fix=workflow.implementation_pending_added")
                # Ensure newer status_option flags exist for admin pages and forms
                if "status_option" in insp.get_table_names():
                    status_cols = {c["name"] for c in insp.get_columns("status_option")}
                    if "executive_approval_required" not in status_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE status_option ADD COLUMN executive_approval_required BOOLEAN DEFAULT FALSE"
                                )
                            )
                        print("schema_fix=status_option.executive_approval_required_added")
                    if "sales_list_number_required" not in status_cols:
                        with engine.begin() as conn:
                            conn.execute(
                                text(
                                    "ALTER TABLE status_option ADD COLUMN sales_list_number_required BOOLEAN DEFAULT FALSE"
                                )
                            )
                        print("schema_fix=status_option.sales_list_number_required_added")
                # Ensure a default workflow exists so guest forms have sensible choices
                try:
                    from app.models import Workflow
                    from app import db

                    if "workflow" in insp.get_table_names():
                        existing = Workflow.query.filter_by(
                            name="Default A→B→C"
                        ).first()
                        spec = _default_workflow_spec()
                        if not existing:
                            w = Workflow(
                                name="Default A→B→C",
                                description="Default handoff workflow between A→B→C",
                                spec=spec,
                                active=True,
                            )
                            db.session.add(w)
                            try:
                                db.session.commit()
                                print("schema_fix=workflow.default_created")
                            except Exception:
                                db.session.rollback()
                        else:
                            existing_steps = []
                            if isinstance(existing.spec, dict):
                                existing_steps = existing.spec.get("steps") or []
                            if any(isinstance(step, str) for step in existing_steps) or not any(
                                isinstance(step, dict) and (step.get("from_dept") or step.get("to_dept"))
                                for step in existing_steps
                            ):
                                existing.spec = spec
                                try:
                                    db.session.commit()
                                    print("schema_fix=workflow.default_normalized")
                                except Exception:
                                    db.session.rollback()
                except Exception:
                    pass

                # if we have any workflows but no status options, bootstrap them
                try:
                    from app.models import StatusOption
                    if (
                        "workflow" in insp.get_table_names()
                        and "status_option" in insp.get_table_names()
                    ):
                        # count existing status options using raw SQL to avoid ORM issues
                        count = 0
                        with engine.begin() as conn:
                            count = conn.execute(text("SELECT count(*) FROM status_option")).scalar()
                        if count == 0:
                            # iterate workflows via ORM (safe because we've imported models)
                            for wf in Workflow.query.all():
                                spec = wf.spec or {}
                                from app.admin.workflows import _normalize_workflow_spec
                                spec = _normalize_workflow_spec(spec, wf.name)
                                steps = spec.get("steps") or []
                                for step in steps:
                                    code = None
                                    target = None
                                    if isinstance(step, dict):
                                        code = step.get("status") or step.get("code")
                                        target = step.get("to_dept") or step.get("to")
                                    elif isinstance(step, str):
                                        code = step
                                    if not code:
                                        continue
                                    label = code.replace("_", " ").title()
                                    params = {"c": code, "l": label}
                                    stmt = "INSERT INTO status_option (code,label"
                                    if target:
                                        stmt += ",target_department"
                                        params["t"] = target
                                    stmt += ") VALUES (:c,:l"
                                    if target:
                                        stmt += ",:t"
                                    stmt += ")"
                                    with engine.begin() as conn:
                                        conn.execute(text(stmt), params)
                            print("schema_fix=status_options_generated_from_workflows")
                except Exception:
                    # don't crash the release process for this bootstrap
                    print("status_options_bootstrap_failed")
        except Exception as exc:
            print("schema_fix_failed", exc, file=sys.stderr)

        # If SSO is enabled for this deployment, skip seeding so real SSO
        # users are authoritative. Otherwise run the local seed to ensure demo
        # accounts are present for UI/login flows.
        sso_enabled = bool(app.config.get("SSO_ENABLED"))
        if sso_enabled:
            print("SSO enabled; skipping seed")
            return

        # Run the idempotent seed script if present
        try:
            import seed

            seed.main()
            print("seeded")
        except Exception as exc:
            print("seed failed", exc, file=sys.stderr)


if __name__ == "__main__":
    main()
