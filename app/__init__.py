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
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", app.config.get("SQLALCHEMY_DATABASE_URI"))

    @app.cli.command("notify-due")
    def notify_due():
        from .notifications.due import send_due_soon_notifications
        send_due_soon_notifications(current_app, hours=24)

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

    # DEV ONLY: auto-create tables
    if os.getenv("AUTO_CREATE_DB", "True") == "True":
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
            return ("Service temporarily unavailable — database initializing. Please try again shortly.", 503)
    except Exception:
        # If SQLAlchemy isn't available for some reason, skip installing the handler.
        pass

    return app