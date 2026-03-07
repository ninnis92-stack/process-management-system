#!/usr/bin/env python3
"""Run DB setup and optional seeding during deploy.

This script is intended to be used as a deploy `release_command` so it runs
once per deployment before new instances receive traffic. It will create
tables (via `db.create_all()`) and run `seed.py` when SSO is not enabled in
the app config (so demo accounts are present for non-SSO deployments).
"""
import sys
import os

sys.path.append('/app')

import sys
from pathlib import Path

# Ensure project root is on sys.path so `from app import create_app` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
import subprocess
from sqlalchemy import inspect, text


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
                print('alembic_upgrade=ok')
            else:
                print('alembic_upgrade=failed', rc.returncode)
        except FileNotFoundError:
            # Alembic binary not available; skip with a warning.
            print('alembic not found; skipping migrations')
        except Exception as exc:
            print('alembic_upgrade_exception', exc, file=sys.stderr)

        # Safety net for environments where Alembic is not configured (e.g. no
        # alembic.ini in image) so deployments still converge on required schema.
        try:
            db = app.extensions.get('sqlalchemy')
            if db is not None:
                db.create_all()
                engine = db.engine
                insp = inspect(engine)

                # Ensure legacy deployments have expected request columns.
                req_cols = {c['name'] for c in insp.get_columns('request')}
                if 'sales_list_reference' not in req_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE request ADD COLUMN sales_list_reference VARCHAR(200)'))
                    print('schema_fix=request.sales_list_reference_added')

                submission_cols = {c['name'] for c in insp.get_columns('submission')} if 'submission' in insp.get_table_names() else set()
                if 'submission' in insp.get_table_names() and 'template_id' not in submission_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE submission ADD COLUMN template_id INTEGER'))
                    print('schema_fix=submission.template_id_added')
                if 'submission' in insp.get_table_names() and 'data' not in submission_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE submission ADD COLUMN data JSONB'))
                    print('schema_fix=submission.data_added')

                notification_cols = {c['name'] for c in insp.get_columns('notification')} if 'notification' in insp.get_table_names() else set()
                if 'notification' in insp.get_table_names() and 'read_at' not in notification_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE notification ADD COLUMN read_at TIMESTAMP'))
                    print('schema_fix=notification.read_at_added')

                special_cols = {c['name'] for c in insp.get_columns('special_email_config')} if 'special_email_config' in insp.get_table_names() else set()
                if 'special_email_config' in insp.get_table_names() and 'nudge_min_delay_hours' not in special_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE special_email_config ADD COLUMN nudge_min_delay_hours INTEGER DEFAULT 4'))
                    print('schema_fix=special_email_config.nudge_min_delay_hours_added')
                if 'special_email_config' in insp.get_table_names() and 'request_form_department' not in special_cols:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE special_email_config ADD COLUMN request_form_department VARCHAR(2) DEFAULT 'A'"))
                    print('schema_fix=special_email_config.request_form_department_added')
                if 'special_email_config' in insp.get_table_names() and 'request_form_field_validation_enabled' not in special_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE special_email_config ADD COLUMN request_form_field_validation_enabled BOOLEAN DEFAULT FALSE'))
                    print('schema_fix=special_email_config.request_form_field_validation_enabled_added')
                if 'special_email_config' in insp.get_table_names() and 'request_form_inventory_out_of_stock_notify_enabled' not in special_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE special_email_config ADD COLUMN request_form_inventory_out_of_stock_notify_enabled BOOLEAN DEFAULT FALSE'))
                    print('schema_fix=special_email_config.request_form_inventory_out_of_stock_notify_enabled_added')
                if 'special_email_config' in insp.get_table_names() and 'request_form_inventory_out_of_stock_notify_mode' not in special_cols:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE special_email_config ADD COLUMN request_form_inventory_out_of_stock_notify_mode VARCHAR(20) DEFAULT 'email'"))
                    print('schema_fix=special_email_config.request_form_inventory_out_of_stock_notify_mode_added')
                if 'special_email_config' in insp.get_table_names() and 'request_form_inventory_out_of_stock_message' not in special_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE special_email_config ADD COLUMN request_form_inventory_out_of_stock_message TEXT'))
                    print('schema_fix=special_email_config.request_form_inventory_out_of_stock_message_added')

                status_cols = {c['name'] for c in insp.get_columns('status_option')} if 'status_option' in insp.get_table_names() else set()
                if 'status_option' in insp.get_table_names() and 'email_enabled' not in status_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE status_option ADD COLUMN email_enabled BOOLEAN DEFAULT FALSE'))
                    print('schema_fix=status_option.email_enabled_added')

                department_cols = {c['name'] for c in insp.get_columns('department')} if 'department' in insp.get_table_names() else set()
                if 'department' in insp.get_table_names() and 'order' not in department_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE department ADD COLUMN "order" INTEGER DEFAULT 0'))
                    print('schema_fix=department.order_added')

                site_cols = {c['name'] for c in insp.get_columns('site_config')} if 'site_config' in insp.get_table_names() else set()
                if 'site_config' in insp.get_table_names() and 'brand_name' not in site_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE site_config ADD COLUMN brand_name VARCHAR(120)'))
                    print('schema_fix=site_config.brand_name_added')
                if 'site_config' in insp.get_table_names() and 'logo_filename' not in site_cols:
                    with engine.begin() as conn:
                        conn.execute(text('ALTER TABLE site_config ADD COLUMN logo_filename VARCHAR(255)'))
                    print('schema_fix=site_config.logo_filename_added')
                if 'site_config' in insp.get_table_names() and 'theme_preset' not in site_cols:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE site_config ADD COLUMN theme_preset VARCHAR(40) DEFAULT 'default'"))
                    print('schema_fix=site_config.theme_preset_added')
                # Ensure feature_flags has expected columns added in recent releases.
                if 'feature_flags' in insp.get_table_names():
                    ff_cols = {c['name'] for c in insp.get_columns('feature_flags')}
                    if 'vibe_enabled' not in ff_cols:
                        with engine.begin() as conn:
                            conn.execute(text("ALTER TABLE feature_flags ADD COLUMN vibe_enabled BOOLEAN DEFAULT TRUE"))
                        print('schema_fix=feature_flags.vibe_enabled_added')
                    if 'sso_admin_sync_enabled' not in ff_cols:
                        with engine.begin() as conn:
                            conn.execute(text("ALTER TABLE feature_flags ADD COLUMN sso_admin_sync_enabled BOOLEAN DEFAULT TRUE"))
                        print('schema_fix=feature_flags.sso_admin_sync_enabled_added')
                # Ensure user.last_active_dept exists when model expects it
                if 'user' in insp.get_table_names():
                    user_cols = {c['name'] for c in insp.get_columns('user')}
                    if 'last_active_dept' not in user_cols:
                        with engine.begin() as conn:
                            # quote user as it's a reserved word in some DBs
                            conn.execute(text('ALTER TABLE "user" ADD COLUMN last_active_dept VARCHAR(2)'))
                        print('schema_fix=user.last_active_dept_added')
                # Ensure request.is_denied exists when the model expects it
                if 'request' in insp.get_table_names():
                    req_cols = {c['name'] for c in insp.get_columns('request')}
                    if 'is_denied' not in req_cols:
                        with engine.begin() as conn:
                            conn.execute(text('ALTER TABLE request ADD COLUMN is_denied BOOLEAN DEFAULT FALSE'))
                        print('schema_fix=request.is_denied_added')
        except Exception as exc:
            print('schema_fix_failed', exc, file=sys.stderr)

        # If SSO is enabled for this deployment, skip seeding so real SSO
        # users are authoritative. Otherwise run the local seed to ensure demo
        # accounts are present for UI/login flows.
        sso_enabled = bool(app.config.get('SSO_ENABLED'))
        if sso_enabled:
            print('SSO enabled; skipping seed')
            return

        # Run the idempotent seed script if present
        try:
            import seed
            seed.main()
            print('seeded')
        except Exception as exc:
            print('seed failed', exc, file=sys.stderr)


if __name__ == '__main__':
    main()
