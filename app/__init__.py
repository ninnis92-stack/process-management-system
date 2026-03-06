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
            from .models import SiteConfig
            from flask import url_for
            css = ''
            logo = current_app.config.get('LOGO_URL')

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

            # site config (singleton)
            try:
                cfg = SiteConfig.get()
                banner_html = cfg.banner_html or ''
                rolling_quotes_enabled = bool(cfg.rolling_quotes_enabled)
                rolling_quotes = cfg.rolling_quotes or []
            except Exception:
                banner_html = ''
                rolling_quotes_enabled = False
                rolling_quotes = []

            return dict(active_theme_css=css, theme_logo_url=logo,
                        site_banner_html=banner_html,
                        rolling_quotes_enabled=rolling_quotes_enabled,
                        rolling_quotes=rolling_quotes)
        except Exception:
            return dict(active_theme_css='', theme_logo_url=current_app.config.get('LOGO_URL'),
                        site_banner_html='', rolling_quotes_enabled=False, rolling_quotes=[])

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

    return app