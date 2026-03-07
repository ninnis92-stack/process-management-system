"""Application factory and CLI helpers.

create_app() constructs the Flask application, initializes extensions
(database, login manager, optional Flask-Migrate), registers blueprints,
and sets up development CLI helpers used by maintainers.

This module intentionally keeps initialization deterministic so tests
and local scripts can create the app with `create_app()`.
"""

import os
import click
from dotenv import load_dotenv
from flask import Flask, current_app
from werkzeug.security import generate_password_hash

from config import Config
from .extensions import db, login_manager, migrate
from flask_wtf import CSRFProtect
from .models import User

# Module-level CSRFProtect instance so other modules can use `from app import csrf`
csrf = CSRFProtect()

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    # Allow runtime override of DB URL so tests can monkeypatch env before calling create_app()
    db_url = os.getenv("DATABASE_URL", app.config.get("SQLALCHEMY_DATABASE_URI"))
    # Normalize legacy `postgres://` scheme to SQLAlchemy-compatible `postgresql://`
    if isinstance(db_url, str) and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url

    @app.cli.command("notify-due")
    def notify_due():
        from .notifications.due import send_due_soon_notifications
        send_due_soon_notifications(current_app, hours=24)

    @app.cli.command("notify-nudges")
    def notify_nudges():
        from .notifications.due import send_high_priority_nudges
        send_high_priority_nudges(current_app)

    @app.cli.command("create-user")
    @click.option("--email", required=True, help="User email")
    @click.option("--name", default=None, help="Display name")
    @click.option("--department", default="A", type=click.Choice(["A", "B", "C"], case_sensitive=False))
    @click.option("--password", default="password123", help="Password for local login")
    def create_user_cli(email, name, department, password):
        """Create a local user (dev/test)."""
        email_n = email.strip().lower()
        with app.app_context():
            existing = User.query.filter_by(email=email_n).first()
            if existing:
                click.echo(f"User {email_n} already exists; updating department/name/password")
                existing.department = department.upper()
                existing.name = name or existing.name
                # Avoid relying on environment-specific default hash methods (e.g. scrypt)
                existing.password_hash = generate_password_hash(password, method="pbkdf2:sha256")
                existing.is_active = True
                db.session.commit()
                return
            u = User(
                email=email_n,
                name=name,
                department=department.upper(),
                # Use a compatible hashing method across runtimes
                password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
                is_active=True,
            )
            db.session.add(u)
            db.session.commit()
            click.echo(f"Created {email_n} in Dept {department.upper()}")

    # Init OAuth (SSO)
    from .auth.sso import init_oauth
    init_oauth(app)

    # Optional Sentry initialization (guarded by SENTRY_DSN)
    try:
        from .extensions import init_sentry
        init_sentry(app)
    except Exception:
        pass

    # Optional security headers middleware (guarded by SECURITY_HEADERS_ENABLED env)
    try:
        from .middleware import init_security
        init_security(app)
    except Exception:
        pass

    # Upload folder (best-effort; serverless may not allow writes)
    upload_folder = app.config.get("UPLOAD_FOLDER")
    if upload_folder:
        try:
            os.makedirs(upload_folder, exist_ok=True)
        except OSError:
            pass

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    # Enable CSRF protection for all forms (create module-level instance so
    # individual routes can be exempted when necessary)
    from . import csrf as _csrf  # local import to ensure module-level var exists
    _csrf.init_app(app)

    # Initialize optional caching and Redis client if available.
    try:
        from .extensions import cache, init_redis_client
        try:
            cache.init_app(app, config={
                'CACHE_TYPE': 'redis',
                'CACHE_REDIS_URL': app.config.get('REDIS_URL'),
                'CACHE_DEFAULT_TIMEOUT': app.config.get('CACHE_DEFAULT_TIMEOUT', 300),
            })
        except Exception:
            # If Flask-Caching isn't installed or config invalid, continue without cache.
            try:
                app.logger.info('Cache not initialized (missing package or config)')
            except Exception:
                pass
        try:
            init_redis_client(app)
        except Exception:
            pass
    except Exception:
        # Optional cache/redis not available; proceed.
        pass

    # Initialize Flask-Migrate (Alembic) for DB migrations if available
    try:
        if migrate is not None:
            migrate.init_app(app, db)
    except Exception:
        # If Flask-Migrate isn't installed in this environment, skip init
        pass

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            # If the DB/tables aren't ready (e.g., fresh deploy with SQLite),
            # avoid raising an exception during request handling and treat
            # the visitor as anonymous so the app can return a login page
            # instead of a 500. Specific DB errors (OperationalError) will
            # be surfaced in the logs by SQLAlchemy where appropriate.
            return None

    # Apply impersonation override on each request: if an admin has started an
    # acting-as session, temporarily present them as a member of the target dept.
    @app.before_request
    def _apply_impersonation():
        from flask_login import current_user
        try:
            if not current_user or not getattr(current_user, 'is_authenticated', False):
                return
        except Exception:
            return

        imp_admin = None
        from flask import session as _session
        imp_admin = _session.get('impersonate_admin_id')
        imp_dept = _session.get('impersonate_dept')
        if imp_admin and imp_dept and int(imp_admin) == int(getattr(current_user, 'id', -1)):
            # Override department for permission checks and templates for duration of request.
            try:
                current_user.department = imp_dept
                current_user.is_acting_as = True
                current_user.act_as_label = f"Acting as Dept {imp_dept}"
            except Exception:
                pass
        # Honor a user-selected active department stored in session. This
        # allows users assigned to multiple departments to switch their
        # active context without changing their stored primary department.
        try:
            active_dept = _session.get('active_dept')
            if active_dept:
                # Validate that the current user is allowed to view as this dept
                try:
                    from .models import UserDepartment, Department
                    allowed = False
                    # Always allow switching to primary department
                    if getattr(current_user, 'department', None) == active_dept:
                        allowed = True
                    # Admins may switch freely
                    if getattr(current_user, 'is_admin', False):
                        allowed = True
                    # Otherwise check explicit assignments
                    if not allowed:
                        ud = UserDepartment.query.filter_by(user_id=current_user.id, department=active_dept).first()
                        if ud:
                            allowed = True
                    if allowed:
                        try:
                            current_user.department = active_dept
                            current_user.is_switched_dept = True
                            current_user.act_as_label = f"Viewing as Dept {active_dept}"
                        except Exception:
                            pass
                except Exception:
                    # If any DB error occurs while validating, fall back to no-op
                    pass
        except Exception:
            pass
        return

    from .auth.routes import auth_bp
    from .requests_bp.routes import requests_bp
    from .external.routes import external_bp
    from .notifications.routes import notifications_bp
    from .admin.routes import admin_bp
    from .integrations.webhooks import integrations_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(external_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(integrations_bp)

    # Provide active theme CSS and logo URL to templates
    @app.context_processor
    def _theme_context():
        try:
            from .models import SiteConfig, Department, FeatureFlags
            from flask import url_for
            css = ''
            logo = current_app.config.get('LOGO_URL')
            brand_name = 'FreshProcess'
            site_theme_preset = 'default'
            dept_labels = {'A': 'Dept A', 'B': 'Dept B', 'C': 'Dept C'}

            # Theme model is optional in some environments/tests.
            try:
                from .models import AppTheme
                t = AppTheme.query.filter_by(active=True).first()
                css = t.css if t and t.css else ''
                if t and t.logo_filename:
                    try:
                        if t.logo_filename.startswith('http'):
                            logo = t.logo_filename
                        else:
                            logo = url_for('static', filename=t.logo_filename)
                    except Exception:
                        pass
            except Exception:
                pass

                # If an AppTheme or SiteConfig supplies a custom logo or theme
                # preset, treat that as an "imported" external theme and
                # deactivate the vibe UI by default. We don't persistently
                # modify the DB flag here; instead expose a light wrapper to
                # templates so `FeatureFlags.get().vibe_enabled` will reflect the
                # runtime override while leaving the stored flag untouched.
                external_theme_loaded = False
                try:
                    # AppTheme active with logo or css
                    from .models import AppTheme
                    t_check = AppTheme.query.filter_by(active=True).first()
                    if t_check and (getattr(t_check, 'logo_filename', None) or getattr(t_check, 'css', None)):
                        external_theme_loaded = True
                except Exception:
                    pass
                try:
                    # SiteConfig provides a logo or non-default preset
                    cfg_check = SiteConfig.get()
                    if getattr(cfg_check, 'logo_filename', None):
                        external_theme_loaded = True
                    if getattr(cfg_check, 'theme_preset', None) and (cfg_check.theme_preset or '').strip().lower() != 'default':
                        external_theme_loaded = True
                except Exception:
                    pass

                class _FeatureFlagsProxy:
                    def __init__(self, real_cls, force_vibe=None):
                        self._real = real_cls
                        self._force = force_vibe

                    def get(self):
                        f = self._real.get()
                        if self._force is None:
                            return f
                        # Return a lightweight view object that overrides
                        # `vibe_enabled` while delegating other attributes.
                        class _View:
                            def __init__(self, orig, forced):
                                self._orig = orig
                                self.vibe_enabled = forced

                            def __getattr__(self, name):
                                return getattr(self._orig, name)

                        return _View(f, self._force)

                feature_flags_obj = _FeatureFlagsProxy(FeatureFlags, force_vibe=False if external_theme_loaded else None)

            # site config (singleton)
            try:
                cfg = SiteConfig.get()
                banner_html = cfg.banner_html or ''
                rolling_quotes_enabled = bool(cfg.rolling_quotes_enabled)
                rolling_quotes = cfg.rolling_quotes or []
                if getattr(cfg, 'logo_filename', None):
                    try:
                        logo = url_for('static', filename=cfg.logo_filename)
                    except Exception:
                        pass
                if getattr(cfg, 'brand_name', None):
                    brand_name = cfg.brand_name
                if getattr(cfg, 'theme_preset', None):
                    site_theme_preset = (cfg.theme_preset or 'default').strip().lower()
                    if site_theme_preset not in ('default', 'ocean', 'forest', 'sunset', 'midnight'):
                        site_theme_preset = 'default'
            except Exception:
                banner_html = ''
                rolling_quotes_enabled = False
                rolling_quotes = []

            try:
                rows = Department.query.filter_by(is_active=True).order_by(Department.order.asc(), Department.code.asc()).all()
                for d in rows:
                    code = (d.code or '').upper().strip()
                    label = (d.label or '').strip()
                    if code and label:
                        dept_labels[code] = label
            except Exception:
                pass

            return dict(active_theme_css=css, theme_logo_url=logo,
                        site_brand_name=brand_name,
                        site_theme_preset=site_theme_preset,
                        department_labels=dept_labels,
                        site_banner_html=banner_html,
                        rolling_quotes_enabled=rolling_quotes_enabled,
                        rolling_quotes=rolling_quotes,
                        FeatureFlags=FeatureFlags)
        except Exception:
            return dict(active_theme_css='', theme_logo_url=current_app.config.get('LOGO_URL'),
                        site_brand_name='FreshProcess',
                        site_theme_preset='default',
                        department_labels={'A': 'Dept A', 'B': 'Dept B', 'C': 'Dept C'},
                        site_banner_html='', rolling_quotes_enabled=False, rolling_quotes=[],
                        FeatureFlags=None)

    # Track the last successfully rendered GET URL in the session so that
    # when the DB is temporarily unavailable we can redirect users back to
    # the last working page instead of showing a persistent 503 on refresh.
    from flask import session as _session, request as _request

    @app.after_request
    def _store_last_good(response):
        try:
            # Only store successful GET responses (status < 400).
            if _request.method == 'GET' and response.status_code < 400:
                try:
                    _session['last_good_url'] = _request.url
                except Exception:
                    # Session may be unavailable in some contexts; ignore.
                    pass
        except Exception:
            pass
        return response

    # DEV ONLY: auto-create tables
    # NOTE: For production we prefer running Alembic migrations during the
    # release step. Default AUTO_CREATE_DB is now False to avoid implicit
    # create_all() in deployed instances. Set `AUTO_CREATE_DB=true` locally
    # if you want the convenience behavior during development.
    if os.getenv("AUTO_CREATE_DB", "False") == "True":
        with app.app_context():
            db.create_all()

    # Return a friendly 503 when the database isn't ready instead of a 500.
    # This avoids exposing a stacktrace to end users during rolling deploys
    # when a machine may briefly not have the DB/tables available.
    try:
        from sqlalchemy.exc import OperationalError

        @app.errorhandler(OperationalError)
        def _handle_db_op_error(err):
            app.logger.exception("Database operational error handled: %s", err)
            # If we have a recorded last-good URL in the user's session, try
            # redirecting them there so a browser refresh will return them to
            # a previously loaded page instead of repeatedly showing the 503.
            try:
                from flask import session as _session, redirect, request as _request
                last = _session.get('last_good_url')
                # Avoid redirect loops: don't redirect back to the same failing URL
                if last and last != _request.url:
                    app.logger.info('Redirecting to last good URL after DB error: %s', last)
                    return redirect(last)
            except Exception:
                pass

            return ("Service temporarily unavailable — database initializing. Please try again shortly.", 503)
    except Exception:
        # If SQLAlchemy isn't available for some reason, skip installing the handler.
        pass

    # Friendly handling for expired/invalid CSRF tokens (common during prototyping).
    try:
        from flask_wtf.csrf import CSRFError
        from flask import flash, redirect, url_for

        @app.errorhandler(CSRFError)
        def _handle_csrf_error(err):
            app.logger.warning("CSRF error handled: %s", err)
            # Inform the user and redirect to login where a fresh token will be issued
            flash("Session expired or invalid form submission — please try again.", "warning")
            return redirect(url_for("auth.login"))
    except Exception:
        pass
    except Exception:
        # If SQLAlchemy isn't available for some reason, skip installing the handler.
        pass

    # Lightweight health endpoint used by readiness probes. Returns 200 when
    # the DB responds to a trivial query, otherwise 503.
    from flask import jsonify

    @app.route("/health")
    def _health():
        try:
            # Simple DB check — if this raises, the DB/tables are likely not ready.
            from sqlalchemy import text
            db.session.execute(text("SELECT 1"))
            return (jsonify({"status": "ok"}), 200)
        except Exception as e:
            app.logger.warning("Health check failed: %s", e)
            return (jsonify({"status": "unhealthy"}), 503)

    # Optionally wait for DB readiness during app startup. When the
    # `WAIT_FOR_DB` env var is set to a truthy value, the application will
    # attempt a simple `SELECT 1` repeatedly before returning the app
    # instance. This is helpful for deployments where the DB may not be
    # immediately reachable at process start (e.g. cloud services).
    if os.getenv("WAIT_FOR_DB", "False") == "True":
        import time
        from sqlalchemy import text
        with app.app_context():
            for _ in range(30):
                try:
                    db.session.execute(text("SELECT 1"))
                    app.logger.info("Database reachable, continuing startup")
                    break
                except Exception:
                    app.logger.info("Waiting for database to become available...")
                    time.sleep(2)
            else:
                app.logger.warning("Timed out waiting for database (proceeding anyway)")

    # Ensure recommended default buckets exist for Dept B unless explicitly disabled.
    # This provides sensible defaults for the Dept B dashboard when a fresh DB
    # is created or when a deploy doesn't include seeded data. Admins can still
    # edit or replace buckets via the admin UI.
    try:
        if os.getenv("SEED_DEFAULT_BUCKETS", "True").lower() != "false":
            from .models import StatusBucket, BucketStatus, Department
            try:
                with app.app_context():
                    # Ensure default Department rows exist (A/B/C) so code treating
                    # them as persisted departments behaves consistently.
                    for code, label, order in (('A', 'Dept A', 0), ('B', 'Dept B', 1), ('C', 'Dept C', 2)):
                        existing = Department.query.filter_by(code=code).first()
                        if not existing:
                            d = Department(code=code, label=label, is_active=True, order=order)
                            db.session.add(d)
                    db.session.flush()

                    # Only seed buckets if Dept B has no buckets configured.
                    if StatusBucket.query.filter_by(department_name='B').count() == 0:
                        # New
                        nb = StatusBucket(name='New', department_name='B', order=0, active=True)
                        db.session.add(nb)
                        db.session.flush()
                        db.session.add(BucketStatus(bucket_id=nb.id, status_code='NEW_FROM_A', order=0))

                        # In Progress
                        ip = StatusBucket(name='In Progress', department_name='B', order=1, active=True)
                        db.session.add(ip)
                        db.session.flush()
                        db.session.add(BucketStatus(bucket_id=ip.id, status_code='B_IN_PROGRESS', order=0))
                        db.session.add(BucketStatus(bucket_id=ip.id, status_code='PENDING_C_REVIEW', order=1))
                        db.session.add(BucketStatus(bucket_id=ip.id, status_code='B_FINAL_REVIEW', order=2))

                        # Needs Input / Waiting
                        ni = StatusBucket(name='Needs Input', department_name='B', order=2, active=True)
                        db.session.add(ni)
                        db.session.flush()
                        db.session.add(BucketStatus(bucket_id=ni.id, status_code='WAITING_ON_A_RESPONSE', order=0))
                        db.session.add(BucketStatus(bucket_id=ni.id, status_code='C_NEEDS_CHANGES', order=1))

                        # Pending Approval
                        pa = StatusBucket(name='Pending Approval', department_name='B', order=3, active=True)
                        db.session.add(pa)
                        db.session.flush()
                        db.session.add(BucketStatus(bucket_id=pa.id, status_code='EXEC_APPROVAL', order=0))
                        db.session.add(BucketStatus(bucket_id=pa.id, status_code='C_APPROVED', order=1))
                        db.session.add(BucketStatus(bucket_id=pa.id, status_code='SENT_TO_A', order=2))

                        # Completed
                        comp = StatusBucket(name='Completed', department_name='B', order=4, active=True)
                        db.session.add(comp)
                        db.session.flush()
                        db.session.add(BucketStatus(bucket_id=comp.id, status_code='CLOSED', order=0))

                        # Archived (placeholder)
                        arch = StatusBucket(name='Archived', department_name='B', order=5, active=True)
                        db.session.add(arch)

                    db.session.commit()
                    app.logger.info('Seeded default departments and Dept B buckets')
            except Exception:
                app.logger.exception('Failed to seed default Dept B buckets or departments')
    except Exception:
        # Best-effort; avoid failing app startup if env inspection or imports fail.
        pass

    return app